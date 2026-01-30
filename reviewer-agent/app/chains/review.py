"""Review chain: issue + diff + CI + code context -> reviewer summary, requirements_met, issues_found."""
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import ReviewSummaryOutput
from ..prompts import REVIEW_SYSTEM, REVIEW_HUMAN


def create_review_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for reviewing a PR against an issue.

    Input: issue_title, issue_body, coding_agent_summary, diff, ci_status, code_context
    Output: ReviewSummaryOutput (reviewer_summary, requirements_met, issues_found)
    """
    parser = PydanticOutputParser(pydantic_object=ReviewSummaryOutput)
    prompt = ChatPromptTemplate.from_messages([
        ("system", REVIEW_SYSTEM),
        ("human", REVIEW_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())
    return prompt | llm | parser
