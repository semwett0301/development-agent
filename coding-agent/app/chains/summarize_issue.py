from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import IssueSummaryOutput
from ..prompts import SUMMARY_ISSUE_SYSTEM, SUMMARY_ISSUE_HUMAN


def create_summarize_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for summarizing GitHub issues. Prompts are from prompts/summary_issue.py

    Input:
        llm: The LangChain chat model to use

    Output:
        A chain that takes {title, body, labels} and returns IssueSummaryOutput
    """
    parser = PydanticOutputParser(pydantic_object=IssueSummaryOutput)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SUMMARY_ISSUE_SYSTEM),
        ("human", SUMMARY_ISSUE_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser
