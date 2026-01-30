"""
ReviewService: orchestration for reviewing a PR against Issue, diff, CI.
"""
import logging
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
        # 1. Fetch PR, issue, diff, check runs
        pr = self._github.get_pull_request(owner, repo, pr_number)
        diff = self._github.get_pull_request_diff(owner, repo, pr_number)
        check_runs = self._github.get_check_runs_for_ref(
            owner, repo, pr.head_sha)

        issue_number = parse_issue_number_from_pr(
            pr.body, pr.title) or pr_number
        issue_title, issue_body = self._fetch_issue_context(
            owner, repo, issue_number, pr)
        coding_agent_summary = parse_coding_summary_from_pr_body(pr.body)

        code_context = "No code context available."

        ci_status = _format_ci_status(check_runs)
        ci_passed = _ci_passed(check_runs, self.config.ci_required)

        # 2. Track review count
        current_review_count = parse_review_count_from_pr_body(pr.body)
        new_review_count = current_review_count + 1
        logger.info(f"Review attempt #{new_review_count} for PR #{pr_number}")

        # 3. Review chain
        review_output = self._run_review_chain(
            issue_title, issue_body, diff, ci_status, code_context, coding_agent_summary)

        reviewer_summary = review_output.reviewer_summary
        requirements_met = review_output.requirements_met
        issues_found = review_output.issues_found or []

        # 4. Summary similarity (coding_agent vs reviewer)
        summary_similarity = self._compute_similarity(
            coding_agent_summary, reviewer_summary)
        similarity_ok = summary_similarity >= self.config.summary_similarity_threshold

        # 5. is_normal
        is_normal = (
            ci_passed
            and requirements_met
            and similarity_ok
            and len(issues_found) == 0
        )

        # 6. If not normal, run errors chain
        errors = self._extract_errors(
            is_normal, issues_found, diff, check_runs) if not is_normal else []

        # 7. Update PR description with review count
        updated_body = update_review_count_in_body(pr.body, new_review_count)
        
        # 8. Handle based on result
        if is_normal and ci_passed:
            # Success! Approve the PR
            logger.info(f"PR #{pr_number} passed review - approving")
            self._github.update_pull_request(owner, repo, pr_number, updated_body)
            self._github.approve_pull_request(
                owner, repo, pr_number,
                f"✅ Review passed! (attempt #{new_review_count})\n\n"
                f"- CI: ✅ Passed\n"
                f"- Requirements: ✅ Met\n"
                f"- Summary similarity: {summary_similarity:.2f}"
            )
        elif new_review_count >= self.MAX_REVIEW_ATTEMPTS and not ci_passed:
            # Max attempts reached, pipelines still failing
            logger.warning(f"PR #{pr_number} failed after {new_review_count} attempts - giving up")
            updated_body = add_review_failed_message(updated_body, self.MAX_REVIEW_ATTEMPTS)
            self._github.update_pull_request(owner, repo, pr_number, updated_body)
            self._github.request_changes(
                owner, repo, pr_number,
                f"❌ После {self.MAX_REVIEW_ATTEMPTS} попыток ревью пайплайны всё ещё падают.\n\n"
                f"Требуется ручное вмешательство.\n\n"
                f"**Ошибки CI:**\n{ci_status}"
            )
        else:
            # Update count, continue trying
            logger.info(f"PR #{pr_number} needs fixes (attempt #{new_review_count}/{self.MAX_REVIEW_ATTEMPTS})")
            self._github.update_pull_request(owner, repo, pr_number, updated_body)

        return ReviewResult(
            is_normal=is_normal,
            requirements_met=requirements_met,
            ci_passed=ci_passed,
            summary_similarity=summary_similarity,
            reviewer_summary=reviewer_summary,
            coding_agent_summary=coding_agent_summary,
            errors=errors,
        )

    def _fetch_issue_context(self, owner: str, repo: str, issue_number: int, pr) -> tuple[str, str]:
        """Fetch issue title and body, falling back to PR data."""
        try:
            issue_data = self._github.get_issue(owner, repo, issue_number)
        except Exception:
            issue_data = {"title": pr.title, "body": pr.body or ""}
        return issue_data.get("title", pr.title), issue_data.get("body", "") or ""

    def _run_review_chain(self, issue_title: str, issue_body: str, diff: str,
                          ci_status: str, code_context: str,
                          coding_agent_summary: Optional[str]) -> ReviewSummaryOutput:
        """Run the LLM review chain."""
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
            logger.warning("Embedding/similarity failed: %s", e)
            return 1.0

    def _extract_errors(self, is_normal: bool, issues_found: list[str],
                        diff: str, check_runs: list[dict]) -> list[ReviewError]:
        """Run errors chain to produce structured review errors."""
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
            logger.warning("Errors chain failed: %s", e)
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
                logger.warning("Embedding/similarity failed: %s", e)
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
