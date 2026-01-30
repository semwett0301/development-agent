from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import CodeGenerationOutput
from ..prompts import GENERATE_CODE_SYSTEM, GENERATE_CODE_HUMAN, ACTION_INSTRUCTIONS


def create_generate_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for generating code changes. Prompts are from prompts/generate_code.py

    Input:
        llm: The LangChain chat model to use

    Output:
        A chain that takes {step_description, step_details, file_path, action,
        current_content, related_context, conventions, action_instructions}
        and returns CodeGenerationOutput
    """
    parser = PydanticOutputParser(pydantic_object=CodeGenerationOutput)

    prompt = ChatPromptTemplate.from_messages([
        ("system", GENERATE_CODE_SYSTEM),
        ("human", GENERATE_CODE_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())

    return prompt | llm | parser


def get_action_instructions(action: str) -> str:
    """
    Get action-specific instructions for code generation.

    Input:
        action: The action type ('create', 'modify', 'delete')

    Output:
        Instructions string for the specified action

    """
    return ACTION_INSTRUCTIONS.get(action, ACTION_INSTRUCTIONS["modify"])
