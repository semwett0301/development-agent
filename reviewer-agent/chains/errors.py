"""Errors chain: problems + diff/CI -> JSON list of file_path, lines, fix_summary."""
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import ReviewErrorsOutput
from ..prompts import ERRORS_SYSTEM, ERRORS_HUMAN


def create_errors_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain that turns review problems into structured errors (file_path, lines, fix_summary).

    Input: problems, diff, ci_details
    Output: ReviewErrorsOutput (list of errors)
    """
    parser = PydanticOutputParser(pydantic_object=ReviewErrorsOutput)
    prompt = ChatPromptTemplate.from_messages([
        ("system", ERRORS_SYSTEM),
        ("human", ERRORS_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())
    return prompt | llm | parser
