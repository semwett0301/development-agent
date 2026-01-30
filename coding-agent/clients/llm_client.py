import logging
from typing import Optional, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from ..config import LLMConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def create_chat_model(config: LLMConfig) -> BaseChatModel:
    """
    Create a LangChain chat model from config.
    
    Input:
        config: LLMConfig instance
        
    Output:
        A configured BaseChatModel instance
    """
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=config.model,
            api_key=config.api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except ImportError:
        raise ImportError(
            "langchain-anthropic not installed. Run: pip install langchain-anthropic"
        )


class LLMClient:
    """
    Client for interacting with LLM providers via LangChain.
    
    Provides both simple completion and structured output with Pydantic parsing.
    """

    def __init__(self, config: LLMConfig, langfuse_callbacks: Optional[list] = None):
        self.config = config
        self._llm = create_chat_model(config)
        self._langfuse_callbacks = langfuse_callbacks

    @property
    def llm(self) -> BaseChatModel:
        """Get the underlying LangChain chat model."""
        return self._llm

    def complete(self, prompt: str, system_prompt: Optional[str] = None, temperature: Optional[float] = None) -> str:
        """Generate a completion from the LLM."""
        llm = self._llm
        
        # If temperature override, create new model with that temperature
        if temperature is not None and temperature != self.config.temperature:
            llm = create_chat_model(
                LLMConfig(
                    provider=self.config.provider,
                    model=self.config.model,
                    api_key=self.config.api_key,
                    max_tokens=self.config.max_tokens,
                    temperature=temperature,
                )
            )

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        logger.debug(f"LLM request: model={self.config.model}")
        
        kwargs = {}
        if self._langfuse_callbacks:
            kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        response = llm.invoke(messages, **kwargs)
        return response.content

    def complete_structured(self, prompt_template: str, output_model: Type[T], variables: dict, system_prompt: Optional[str] = None) -> T:
        """Generate a structured response parsed into a Pydantic model.
        
        This uses PydanticOutputParser for automatic JSON parsing and validation.
        
        Input:
            prompt_template: The ChatPromptTemplate to use
            output_model: Pydantic model class for the expected output
            variables: Dictionary of variables to fill the template
            system_prompt: Optional system prompt for context
            
        Output:
            A parsed Pydantic model instance
        """
        parser = PydanticOutputParser(pydantic_object=output_model)
        
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        
        messages.append(("human", prompt_template))
        
        chain = ChatPromptTemplate.from_messages(messages) | self._llm | parser
        
        logger.debug(f"Structured LLM request: model={self.config.model}, output={output_model.__name__}")
        
        kwargs = {}
        if self._langfuse_callbacks:
            kwargs["config"] = {"callbacks": self._langfuse_callbacks}
        return chain.invoke(variables, **kwargs)

    def create_chain(self, prompt_template: ChatPromptTemplate, output_model: Optional[Type[T]] = None) -> Runnable:
        """
        Create a reusable chain with optional structured output.
        
        Input:
            prompt_template: The ChatPromptTemplate to use
            output_model: Optional Pydantic model for structured output
            
        Output:
            A chain that can be invoked with variables
        """
        parser = PydanticOutputParser(pydantic_object=output_model) if output_model else StrOutputParser()
        return prompt_template | self._llm | parser
