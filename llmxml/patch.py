import inspect
from enum import Enum
from typing import Any, Callable, Type, TypeVar, Union

from pydantic import BaseModel

from .parser import parse_xml
from .prompts import generate_prompt_template

T = TypeVar("T", bound=BaseModel)


class Mode(Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


def is_async_function(func: Callable[..., Any]) -> bool:
    """Returns true if the callable is async, accounting for wrapped callables"""
    is_coroutine = inspect.iscoroutinefunction(func)
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__  # type: ignore - dynamic
        is_coroutine = is_coroutine or inspect.iscoroutinefunction(func)
    return is_coroutine


def _extract_content(response: Any) -> str:
    """
    Extract the main content from the response depending on provider.
    Adjust as needed based on the actual response structure.
    """
    # Anthropic structure:
    # response.content[0].text
    if (
        hasattr(response, "content")
        and response.content
        and hasattr(response.content[0], "text")
    ):
        return response.content[0].text

    # OpenAI structure:
    # response.choices[0].message.content
    if (
        hasattr(response, "choices")
        and response.choices
        and hasattr(response.choices[0], "message")
    ):
        return response.choices[0].message.content

    # Gemini-like structure:
    # response = {"candidates": [{"content": "..."}]}
    if hasattr(response, "candidates") and response.candidates:
        first_candidate = response.candidates[0]
        if isinstance(first_candidate, dict):
            return first_candidate.get("content", "")

    # Check dict variants
    if isinstance(response, dict):
        if "content" in response and response["content"]:
            return response["content"][0]["text"]
        if "choices" in response and response["choices"]:
            return response["choices"][0]["message"]["content"]
        if "candidates" in response and response["candidates"]:
            return response["candidates"][0].get("content", "")

    # Fallback: just convert to string
    return str(response)


PromptGenerator = Callable[[str], str]


class BasePatchedClient:
    """
    Base class for patched clients.
    Provides common logic for inserting prompts and parsing responses.
    """

    def __init__(
        self, client: Any, mode: Mode, custom_prompt: PromptGenerator | None = None
    ):
        self.client = client
        self.mode = mode
        self.custom_prompt = custom_prompt
        self._orig_method = None
        self._patch_client()

    def _patch_client(self):
        if self.mode == Mode.OPENAI:
            self._patch_openai()
        elif self.mode == Mode.GEMINI:
            self._patch_gemini()
        elif self.mode == Mode.ANTHROPIC:
            self._patch_anthropic()
        else:
            raise ValueError("Unsupported mode")

    def _patch_openai(self):
        create_func = getattr(self.client.chat.completions, "create", None)
        if create_func is None:
            raise AttributeError("OpenAI client does not have chat.completions.create")
        self._orig_method = create_func

    def _patch_gemini(self):
        if hasattr(self.client, "generate_content_async") and is_async_function(
            self.client.generate_content_async
        ):
            self._orig_method = self.client.generate_content_async
        elif hasattr(self.client, "generate_content"):
            self._orig_method = self.client.generate_content
        else:
            raise AttributeError(
                "Gemini client does not have a suitable generate_content method"
            )

    def _patch_anthropic(self):
        create_func = getattr(self.client.messages, "create", None)
        if create_func is None and hasattr(self.client, "beta"):
            create_func = getattr(self.client.beta.messages, "create", None)
        if create_func is None:
            raise AttributeError("Anthropic client does not have messages.create")
        self._orig_method = create_func

    def _insert_prompt(self, response_model: Type[T], kwargs: dict) -> None:
        """Insert a user prompt for the given response_model."""
        schema = generate_prompt_template(response_model, include_instructions=False)
        prompt = (
            self.custom_prompt(schema)
            if self.custom_prompt is not None
            else generate_prompt_template(response_model)
        )

        if "messages" in kwargs and isinstance(kwargs["messages"], list):
            kwargs["messages"].insert(0, {"role": "user", "content": prompt})


class SyncPatchedClient(BasePatchedClient):
    """
    Synchronous patched client.
    `create` method will be synchronous.
    """

    @property
    def chat(self) -> "SyncPatchedClient":
        return self

    @property
    def completions(self) -> "SyncPatchedClient":
        return self

    @property
    def messages(self) -> "SyncPatchedClient":
        return self

    def create(self, response_model: Type[T] = None, **kwargs) -> T | Any:
        if response_model:
            self._insert_prompt(response_model, kwargs)

        response = self._orig_method(**kwargs)
        if response_model:
            content = _extract_content(response)
            return parse_xml(content, response_model)
        return response


class AsyncPatchedClient(BasePatchedClient):
    """
    Asynchronous patched client.
    `create` method will be async and await the original async method.
    """

    @property
    def chat(self) -> "AsyncPatchedClient":
        return self

    @property
    def completions(self) -> "AsyncPatchedClient":
        return self

    @property
    def messages(self) -> "AsyncPatchedClient":
        return self

    async def create(self, response_model: Type[T] = None, **kwargs) -> T | Any:
        if response_model:
            self._insert_prompt(response_model, kwargs)

        response = await self._orig_method(**kwargs)
        if response_model:
            content = _extract_content(response)
            return parse_xml(content, response_model)
        return response


def from_openai(
    client: Any, custom_prompt: PromptGenerator | None = None
) -> Union[SyncPatchedClient, AsyncPatchedClient]:
    dummy = client.chat.completions.create
    is_async = is_async_function(dummy)
    if is_async:
        return AsyncPatchedClient(client, Mode.OPENAI, custom_prompt=custom_prompt)
    return SyncPatchedClient(client, Mode.OPENAI, custom_prompt=custom_prompt)


def from_anthropic(
    client: Any, custom_prompt: PromptGenerator | None = None
) -> Union[SyncPatchedClient, AsyncPatchedClient]:
    # Detect async or sync based on messages.create
    create_func = None
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        create_func = client.messages.create
    elif (
        hasattr(client, "beta")
        and hasattr(client.beta, "messages")
        and hasattr(client.beta.messages, "create")
    ):
        create_func = client.beta.messages.create

    if create_func is None:
        raise AttributeError("Anthropic client does not have messages.create")

    if is_async_function(create_func):
        return AsyncPatchedClient(client, Mode.ANTHROPIC, custom_prompt=custom_prompt)
    return SyncPatchedClient(client, Mode.ANTHROPIC, custom_prompt=custom_prompt)


def from_gemini(
    client: Any, custom_prompt: PromptGenerator | None = None
) -> Union[SyncPatchedClient, AsyncPatchedClient]:
    # TODO: fix. rn just use the gemini api through the openai client. look at the docs for more.
    if hasattr(client, "generate_content_async") and is_async_function(
        client.generate_content_async
    ):
        return AsyncPatchedClient(client, Mode.GEMINI, custom_prompt=custom_prompt)
    elif hasattr(client, "generate_content") and is_async_function(
        client.generate_content
    ):
        return AsyncPatchedClient(client, Mode.GEMINI, custom_prompt=custom_prompt)
    elif hasattr(client, "generate_content"):
        return SyncPatchedClient(client, Mode.GEMINI, custom_prompt=custom_prompt)
    else:
        raise AttributeError("Gemini client does not have a suitable generation method")
