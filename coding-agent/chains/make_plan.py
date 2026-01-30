from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..models import ActionPlanOutput
from ..prompts import MAKE_PLAN_SYSTEM, MAKE_PLAN_HUMAN


def create_plan_chain(llm: BaseChatModel) -> Runnable:
    """
    Create a chain for generating action plans. Prompts are from prompts/make_plan.py
    
    Input:
        llm: The LangChain chat model to use
        
    Output:
        A chain that takes {summary, requirements, acceptance_criteria, 
        code_context, project_structure} and returns ActionPlanOutput
    """
    parser = PydanticOutputParser(pydantic_object=ActionPlanOutput)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", MAKE_PLAN_SYSTEM),
        ("human", MAKE_PLAN_HUMAN),
    ]).partial(format_instructions=parser.get_format_instructions())
    
    return prompt | llm | parser
