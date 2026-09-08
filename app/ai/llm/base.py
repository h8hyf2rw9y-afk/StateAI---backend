"""
The interface every LLM provider implements. An agent (see
app/ai/lead_intelligence_agent.py) holds a reference to this abstract type,
never to a concrete provider class — that's the whole mechanism for "swap
providers without rewriting the agent".
"""

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class LLMProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """The concrete model identifier in use — for logging/attribution only, never shown to the LLM itself."""

    @abstractmethod
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
        max_tokens: int = 1024,
    ) -> ResponseModelT:
        """
        Ask the model to respond to `user_prompt` (under `system_prompt`) and
        return an instance of `response_model` — validated against that
        Pydantic schema, never raw text handed back for the caller to parse.

        Must raise a subclass of app.ai.llm.errors.LLMError on any failure
        (missing configuration, timeout, a provider-side error, or output
        that fails validation against `response_model`) — never let a
        vendor-specific SDK exception escape this method.
        """
