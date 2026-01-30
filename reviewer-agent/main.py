"""
Reviewing Agent — review PRs against Issue, diff, and CI.

Usage:
  python -m reviewing_agent.main --owner OWNER --repo REPO --pr PR_NUMBER
  or: review_pr(owner, repo, pr_number)
"""
import json
import logging
from typing import Optional

from .config import ReviewAgentConfig, load_config
from .models import ReviewResult
from .services import ReviewService
from .clients import flush_langfuse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _observe_if_available(fn):
    """Wrap in Langfuse @observe when available so the full review is one trace."""
    try:
        from langfuse import observe
        return observe(name="reviewing_agent_run")(fn)
    except ImportError:
        return fn


@_observe_if_available
def review_pr(owner: str, repo: str, pr_number: int, config: Optional[ReviewAgentConfig] = None) -> ReviewResult:
    """
    Run the reviewing agent on a pull request.

    Input:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        config: Optional config (default: load_config())

    Output:
        ReviewResult with is_normal, requirements_met, ci_passed, summary_similarity, errors
    """
    config = config or load_config()
    service = ReviewService(config)
    result = service.review_pr(owner, repo, pr_number)
    if config.langfuse and config.langfuse.is_configured:
        flush_langfuse()
    return result


def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the Reviewing Agent on a pull request",
    )
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--pr", type=int, required=True,
                        help="Pull request number")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    args = parser.parse_args()

    result = review_pr(args.owner, args.repo, args.pr)

    if args.json:
        out = {
            "is_normal": result.is_normal,
            "requirements_met": result.requirements_met,
            "ci_passed": result.ci_passed,
            "summary_similarity": result.summary_similarity,
            "reviewer_summary": result.reviewer_summary,
            "coding_agent_summary": result.coding_agent_summary,
            "errors": [
                {
                    "file_path": e.file_path,
                    "lines": e.lines,
                    "fix_summary": e.fix_summary,
                }
                for e in result.errors
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"is_normal: {result.is_normal}")
        print(f"requirements_met: {result.requirements_met}")
        print(f"ci_passed: {result.ci_passed}")
        print(f"summary_similarity: {result.summary_similarity:.4f}")
        print(f"reviewer_summary: {result.reviewer_summary}")
        if result.errors:
            print("errors:")
            for e in result.errors:
                print(f"  - {e.file_path} lines {e.lines}: {e.fix_summary}")


if __name__ == "__main__":
    _main()
