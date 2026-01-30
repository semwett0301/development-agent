from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser, JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import CodeFixesOutput, LintErrorOutput, TestErrorOutput
from ..prompts import FIX_CODE_SYSTEM, FIX_CODE_HUMAN, PARSE_LINT_ERRORS_PROMPT, PARSE_TEST_ERRORS_PROMPT


def create_fix_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for fixing code errors. Prompts are from prompts/fix_code.py

    Input:
        llm: The LangChain chat model to use

    Output:
        A chain that takes {error_summary, lint_output, test_output, files_with_errors, file_contents} and returns CodeFixesOutput
    """
    parser = PydanticOutputParser(pydantic_object=CodeFixesOutput)

    prompt = ChatPromptTemplate.from_messages([
        ("system", FIX_CODE_SYSTEM),
        ("human", FIX_CODE_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser


def create_parse_lint_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for parsing lint error output. Uses PARSE_LINT_ERRORS_PROMPT from prompts/fix_code.py.

    Input:
        llm: The LangChain chat model to use

    Output:
        A chain that takes {lint_output} and returns list of error dicts
    """
    prompt = ChatPromptTemplate.from_template(PARSE_LINT_ERRORS_PROMPT)
    return prompt | llm | JsonOutputParser()


def create_parse_test_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for parsing test error output.

    Uses PARSE_TEST_ERRORS_PROMPT from prompts/fix_code.py.

    Input:
        llm: The LangChain chat model to use

    Output:
        A chain that takes {test_output} and returns list of error dicts
    """
    prompt = ChatPromptTemplate.from_template(PARSE_TEST_ERRORS_PROMPT)
    return prompt | llm | JsonOutputParser()
