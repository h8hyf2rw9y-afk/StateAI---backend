"""
The only LLMProvider implementation that exists today. See base.py for why
no agent imports this module directly — everything here is reached only
through app/ai/llm/factory.py.

Structured output is obtained by forcing a single tool call whose input
schema is the requested Pydantic model's own JSON schema (Anthropic's
documented pattern for reliable structured output: `tool_choice` with a
specific tool name), rather than asking the model to emit JSON in prose and
hoping it parses cleanly.
"""

import anthropic
from pydantic import ValidationError

from app.ai.llm.base import LLMProvider, ResponseModelT
from app.ai.llm.errors import LLMInvalidOutputError, LLMProviderError, LLMTimeoutError

_TOOL_NAME = "record_structured_response"


class AnthropicProvider(LLMProvider):
    def __init__(self, *, api_key: str, model: str, timeout: float = 30.0) -> None:
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    @property
    def model_name(self) -> str:
        return self._model

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[ResponseModelT], max_tokens: int = 1024
    ) -> ResponseModelT:
        tool = {
            "name": _TOOL_NAME,
            "description": f"Record the structured result as {response_model.__name__}.",
            "input_schema": response_model.model_json_schema(),
        }
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
        # APITimeoutError subclasses APIError — must be caught first.
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError("The Anthropic API did not respond in time.") from exc
        except anthropic.APIError as exc:
            raise LLMProviderError(f"The Anthropic API returned an error: {exc}") from exc

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise LLMInvalidOutputError("The model did not return the requested structured output.")

        try:
            return response_model.model_validate(tool_use.input)
        except ValidationError as exc:
            raise LLMInvalidOutputError(f"The model's output failed schema validation: {exc}") from exc
