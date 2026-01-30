"""
ReviewService: orchestration for reviewing a PR against Issue, diff, CI.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from langchain_core.language_models import BaseChatModel

from ..config import ReviewAgentConfig
from ..models import (
    ReviewResult,
    ReviewError,
    ReviewSummaryOutput,
)
from ..clients import (
    GitHubClient,
    create_chat_model,
    get_langfuse_callback,
    parse_coding_summary_from_pr_body,
    parse_issue_number_from_pr,
    parse_review_count_from_pr_body,
    update_review_count_in_body,
    add_review_failed_message,
)
from ..chains import create_review_chain, create_errors_chain
from ..embedding import embed, cosine_similarity

logger = logging.getLogger(__name__)

MAX_REVIEW_ATTEMPTS = 4
REVIEW_COUNT_MARKER = "<!-- reviewer-agent-count:"
FAILED_MARKER = "<!-- reviewer-agent-failed -->"


def _parse_review_count(body: Optional[str]) -> int:
    """Parse review count from PR body."""
    if not body:
        return 0
    match = re.search(r"<!-- reviewer-agent-count:(\d+) -->", body)
    return int(match.group(1)) if match else 0


def _update_review_count_in_body(body: Optional[str], count: int) -> str:
    """Update or add review count marker in PR body."""
    body = body or ""
    marker = f"<!-- reviewer-agent-count:{count} -->"

    if REVIEW_COUNT_MARKER in body:
        # Replace existing marker
        return re.sub(
            r"<!-- reviewer-agent-count:\d+ -->",
            marker,
            body
        )
    # Add marker at the end
    return f"{body}\n\n{marker}"


def _add_failed_message(body: str) -> str:
    """Add failure message to PR body."""
    if FAILED_MARKER in body:
        return body  # Already has failed marker

    failed_message = (
        "\n\n---\n"
        "⚠️ **Reviewer Agent**: После 4 попыток ревью пайплайны всё ещё падают. "
        "Требуется ручное вмешательство.\n"
        f"{FAILED_MARKER}"
    )
    return body + failed_message


def _format_ci_status(check_runs: list[dict]) -> str:
    """Format check runs for the prompt."""
    if not check_runs:
        return "No check runs reported for this commit."
    lines = []
    for run in check_runs:
        name = run.get("name", "unknown")
        status = run.get("status", "unknown")
        conclusion = run.get("conclusion") or "pending"
        lines.append(f"- {name}: status={status}, conclusion={conclusion}")
    return "\n".join(lines)


def _ci_passed(check_runs: list[dict], ci_required: bool) -> bool:
    """True if all check runs are success/neutral/skipped; if no runs, return not ci_required."""
    if not check_runs:
        return not ci_required
    for run in check_runs:
        conclusion = (run.get("conclusion") or "").lower()
        if conclusion not in ("success", "neutral", "skipped", "cancelled"):
            return False
    return True


@dataclass
class PRResultParams:
    """Parameters for handling PR result updates."""
    owner: str
    repo: str
    pr_number: int
    pr_body: Optional[str]
    review_count: int
    is_normal: bool
    ci_passed: bool
    ci_status: str
    summary_similarity: float


class ReviewService:
    """Orchestrates fetching PR/issue/diff/CI, review chain, similarity, errors chain."""

    def __init__(self, config: ReviewAgentConfig, llm: Optional[BaseChatModel] = None,
                 github_client: Optional[GitHubClient] = None):
        self.config = config
        self._llm = llm or create_chat_model(config.llm)
        self._github = github_client or GitHubClient(config.github)
        self._langfuse_callbacks = get_langfuse_callback(config.langfuse)
        self._review_chain = create_review_chain(self._llm)
        self._errors_chain = create_errors_chain(self._llm)

    # Maximum review attempts before giving up
    MAX_REVIEW_ATTEMPTS = 4

    def review_pr(self, owner: str, repo: str, pr_number: int) -> ReviewResult:
        """
        Run the full review pipeline for a pull request.

        Returns:
            ReviewResult with is_normal, requirements_met, ci_passed, summary_similarity, errors.
        """
        repo_full = f"{owner}/{repo}"
        logger.info("[review] Start: %s PR #%s", repo_full, pr_number)

        # 1. Fetch PR data and context
        pr_data = self._fetch_pr_data(owner, repo, pr_number)
        pr = pr_data["pr"]
        diff = pr_data["diff"]
        check_runs = pr_data["check_runs"]
        issue_title = pr_data["issue_title"]
        issue_body = pr_data["issue_body"]
        coding_agent_summary = pr_data["coding_agent_summary"]
        ci_status = pr_data["ci_status"]
        ci_passed = pr_data["ci_passed"]
        new_review_count = pr_data["review_count"]

        # 3. Review chain
        code_context = "No code context available."
        logger.info("[review] Running review chain (diff=%s, ci_status=%s chars)", len(
            diff or ""), len(ci_status))
        review_output = self._run_review_chain(
            issue_title, issue_body, diff, ci_status, code_context, coding_agent_summary)

        reviewer_summary = review_output.reviewer_summary
        requirements_met = review_output.requirements_met
        issues_found = review_output.issues_found or []
        logger.info(
            "[review] Review chain done: requirements_met=%s, issues_found=%s",
            requirements_met,
            len(issues_found),
        )

        # 4. Summary similarity (coding_agent vs reviewer)
        summary_similarity = self._compute_similarity(
            coding_agent_summary, reviewer_summary)
        similarity_ok = summary_similarity >= self.config.summary_similarity_threshold
        logger.info(
            "[review] Summary similarity=%.3f (threshold=%.3f), ok=%s",
            summary_similarity,
            self.config.summary_similarity_threshold,
            similarity_ok,
        )

        # 5. is_normal
        is_normal = (
            ci_passed
            and requirements_met
            and similarity_ok
            and len(issues_found) == 0
        )
        logger.info(
            "[review] Verdict: is_normal=%s (ci_passed=%s, requirements_met=%s, similarity_ok=%s, issues=%s)",
            is_normal,
            ci_passed,
            requirements_met,
            similarity_ok,
            len(issues_found),
        )

        # 6. If not normal, run errors chain
        if not is_normal:
            logger.info(
                "[review] Extracting errors (issues_found=%s)", len(issues_found))
        errors = self._extract_errors(
            is_normal, issues_found, diff, check_runs) if not is_normal else []
        if errors:
            logger.info("[review] Extracted %s structured errors", len(errors))

        # 7. Handle PR updates and approvals
        pr_result_params = PRResultParams(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            pr_body=pr.body,
            review_count=new_review_count,
            is_normal=is_normal,
            ci_passed=ci_passed,
            ci_status=ci_status,
            summary_similarity=summary_similarity,
        )
        self._handle_pr_result(pr_result_params)

        logger.info(
            "[review] Done: is_normal=%s, requirements_met=%s, ci_passed=%s, similarity=%.3f, errors=%s",
            is_normal,
            requirements_met,
            ci_passed,
            summary_similarity,
            len(errors),
        )
        return ReviewResult(
            is_normal=is_normal,
            requirements_met=requirements_met,
            ci_passed=ci_passed,
            summary_similarity=summary_similarity,
            reviewer_summary=reviewer_summary,
            coding_agent_summary=coding_agent_summary,
            errors=errors,
        )

    def _fetch_pr_data(self, owner: str, repo: str, pr_number: int) -> dict:
        """Fetch PR, diff, check runs, issue context, and compute review metadata."""
        async def _fetch():
            pr = await self._github.get_pull_request(owner, repo, pr_number)
            diff = await self._github.get_pull_request_diff(owner, repo, pr_number)
            check_runs = await self._github.get_check_runs_for_ref(
                owner, repo, pr.head_sha)
            return pr, diff, check_runs

        pr, diff, check_runs = asyncio.run(_fetch())
        logger.info(
            "[review] Fetched PR head_sha=%s, diff=%s chars, check_runs=%s",
            pr.head_sha[:7] if pr.head_sha else "?",
            len(diff or ""),
            len(check_runs or []),
        )

        current_review_count = parse_review_count_from_pr_body(pr.body)
        new_review_count = current_review_count + 1
        logger.info("[review] Review attempt #%s for PR #%s",
                    new_review_count, pr_number)

        issue_number = parse_issue_number_from_pr(
            pr.body, pr.title) or pr_number
        issue_title, issue_body = self._fetch_issue_context(
            owner, repo, issue_number, pr)
        coding_agent_summary = parse_coding_summary_from_pr_body(pr.body)
        logger.info(
            "[review] Issue context: issue_number=%s, title_len=%s, coding_summary=%s",
            issue_number,
            len(issue_title or "") + len(issue_body or ""),
            "yes" if coding_agent_summary else "no",
        )

        ci_status = _format_ci_status(check_runs)
        ci_passed = _ci_passed(check_runs, self.config.ci_required)
        logger.info("[review] CI: passed=%s, required=%s",
                    ci_passed, self.config.ci_required)

        return {
            "pr": pr,
            "diff": diff,
            "check_runs": check_runs,
            "issue_title": issue_title,
            "issue_body": issue_body,
            "coding_agent_summary": coding_agent_summary,
            "ci_status": ci_status,
            "ci_passed": ci_passed,
            "review_count": new_review_count,
        }

    def _handle_pr_result(self, params: PRResultParams) -> None:
        """Handle PR updates, approvals, or change requests based on review result."""
        updated_body = update_review_count_in_body(
            params.pr_body, params.review_count)

        if params.is_normal and params.ci_passed:
            logger.info(
                "[review] PR #%s passed review → approving", params.pr_number)

            async def _approve():
                await self._github.update_pull_request(
                    params.owner, params.repo, params.pr_number, updated_body)
                await self._github.approve_pull_request(
                    params.owner,
                    params.repo,
                    params.pr_number,
                    f"✅ Review passed! (attempt #{params.review_count})\n\n"
                    f"- CI: ✅ Passed\n"
                    f"- Requirements: ✅ Met\n"
                    f"- Summary similarity: {params.summary_similarity:.2f}",
                )
            asyncio.run(_approve())
        elif params.review_count >= self.MAX_REVIEW_ATTEMPTS and not params.ci_passed:
            logger.warning(
                "[review] PR #%s failed after %s attempts → giving up, requesting changes",
                params.pr_number,
                params.review_count,
            )
            updated_body = add_review_failed_message(
                updated_body, self.MAX_REVIEW_ATTEMPTS)

            async def _request_changes():
                await self._github.update_pull_request(
                    params.owner, params.repo, params.pr_number, updated_body)
                await self._github.request_changes(
                    params.owner,
                    params.repo,
                    params.pr_number,
                    f"❌ После {
                        self.MAX_REVIEW_ATTEMPTS} попыток ревью пайплайны всё ещё падают.\n\n"
                    f"Требуется ручное вмешательство.\n\n"
                    f"**Ошибки CI:**\n{params.ci_status}",
                )
            asyncio.run(_request_changes())
        else:
            logger.info(
                "[review] PR #%s needs fixes → updating body (attempt %s/%s)",
                params.pr_number,
                params.review_count,
                self.MAX_REVIEW_ATTEMPTS,
            )

            async def _update():
                await self._github.update_pull_request(
                    params.owner, params.repo, params.pr_number, updated_body)
            asyncio.run(_update())

    def _fetch_issue_context(self, owner: str, repo: str, issue_number: int, pr) -> tuple[str, str]:
        """Fetch issue title and body, falling back to PR data."""
        async def _fetch_issue():
            try:
                return await self._github.get_issue(owner, repo, issue_number)
            except Exception:
                return {"title": pr.title, "body": pr.body or ""}
        issue_data = asyncio.run(_fetch_issue())
        return issue_data.get("title", pr.title), issue_data.get("body", "") or ""

    def _run_review_chain(self, issue_title: str, issue_body: str, diff: str,
                          ci_status: str, code_context: str,
                          coding_agent_summary: Optional[str]) -> ReviewSummaryOutput:
        """Run the LLM review chain."""
        logger.debug("[review] Invoking review chain (LLM)")
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        return self._review_chain.invoke(
            {
                "issue_title": issue_title,
                "issue_body": issue_body[:8000],
                "diff": diff[:12000],
                "ci_status": ci_status,
                "code_context": code_context[:6000],
                "coding_agent_summary": coding_agent_summary or "(Not provided)",
            },
            **invoke_kwargs,
        )

    def _compute_similarity(self, coding_agent_summary: Optional[str], reviewer_summary: str) -> float:
        """Compute cosine similarity between coding agent and reviewer summaries."""
        if not coding_agent_summary:
            return 1.0
        try:
            return cosine_similarity(embed(coding_agent_summary), embed(reviewer_summary))
        except Exception as e:
            logger.warning("[review] Embedding/similarity failed: %s", e)
            return 1.0

    def _extract_errors(self, is_normal: bool, issues_found: list[str],
                        diff: str, check_runs: list[dict]) -> list[ReviewError]:
        """Run errors chain to produce structured review errors."""
        logger.debug("[review] Errors chain: problems=%s, diff_len=%s", len(
            issues_found), len(diff or ""))
        problems_text = "\n".join(f"- {p}" for p in issues_found)
        if not problems_text:
            problems_text = "CI failed or requirements not met or summary mismatch."
        ci_details = _format_ci_status(check_runs)
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        try:
            errors_output = self._errors_chain.invoke(
                {
                    "problems": problems_text,
                    "diff": diff[:10000],
                    "ci_details": ci_details[:2000],
                },
                **invoke_kwargs,
            )
            return [
                ReviewError(file_path=e.file_path, lines=e.lines,
                            fix_summary=e.fix_summary)
                for e in errors_output.errors
            ]
        except Exception as e:
            logger.warning("[review] Errors chain failed: %s", e)
            if issues_found:
                return [ReviewError(file_path="", lines=[], fix_summary="; ".join(issues_found))]
            return []

    def review_from_synthetic(
        self,
        issue_title: str,
        issue_body: str,
        coding_agent_summary: str,
        *,
        diff: str = "(No diff — plan-only review. Review based on issue and coding agent summary/plan.)",
        ci_status: str = "No CI runs reported for this review.",
        code_context: str = "No code context available.",
    ) -> ReviewResult:
        """
        Run the review pipeline on synthetic input (no GitHub).
        Used to review coding agent test issue results (summaries + plans) without a real PR.

        Returns:
            ReviewResult with is_normal, requirements_met, reviewer_summary, errors, etc.
        """
        invoke_kwargs = {}
        if self._langfuse_callbacks:
            invoke_kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        coding_agent_for_prompt = coding_agent_summary or "(Not provided)"
        review_output: ReviewSummaryOutput = self._review_chain.invoke(
            {
                "issue_title": issue_title,
                "issue_body": (issue_body or "")[:8000],
                "diff": (diff or "")[:12000],
                "ci_status": ci_status[:2000],
                "code_context": code_context[:6000],
                "coding_agent_summary": coding_agent_for_prompt,
            },
            **invoke_kwargs,
        )
        reviewer_summary = review_output.reviewer_summary
        requirements_met = review_output.requirements_met
        issues_found = review_output.issues_found or []

        summary_similarity = 1.0
        if coding_agent_summary and reviewer_summary:
            try:
                vec_coding = embed(coding_agent_summary[:4000])
                vec_review = embed(reviewer_summary)
                summary_similarity = cosine_similarity(vec_coding, vec_review)
            except Exception as e:
                logger.warning("[review] Embedding/similarity failed: %s", e)
        similarity_ok = summary_similarity >= self.config.summary_similarity_threshold
        ci_passed = True  # No real CI in synthetic mode
        is_normal = (
            ci_passed
            and requirements_met
            and similarity_ok
            and len(issues_found) == 0
        )

        errors: list[ReviewError] = []
        if not is_normal:
            problems_text = "\n".join(f"- {p}" for p in issues_found)
            if not problems_text:
                problems_text = "Requirements not met or summary mismatch."
            try:
                errors_output = self._errors_chain.invoke(
                    {
                        "problems": problems_text,
                        "diff": (diff or "")[:10000],
                        "ci_details": ci_status[:2000],
                    },
                    **invoke_kwargs,
                )
                for e in errors_output.errors:
                    errors.append(
                        ReviewError(
                            file_path=e.file_path,
                            lines=e.lines,
                            fix_summary=e.fix_summary,
                        )
                    )
            except Exception as e:
                logger.warning("Errors chain failed: %s", e)
                if issues_found:
                    errors.append(
                        ReviewError(
                            file_path="",
                            lines=[],
                            fix_summary="; ".join(issues_found),
                        )
                    )

        return ReviewResult(
            is_normal=is_normal,
            requirements_met=requirements_met,
            ci_passed=ci_passed,
            summary_similarity=summary_similarity,
            reviewer_summary=reviewer_summary,
            coding_agent_summary=coding_agent_summary,
            errors=errors,
        )
