"""The model interface. Tests use ScriptedLlm; real runs use an OpenAI-compatible endpoint (Nebius Token Factory, or
the NVIDIA API for pilots).

A model answers in one of two protocols: the benchmark's text protocol (`complete`, arms A and B1 to B3) or native tool
calling (`chat`, arms T and TG).
"""

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

RETRIES = 5  # attempts per request before a busy endpoint stops the run
MAX_WAIT_S = 60.0


class LlmError(RuntimeError):
    """The endpoint could not give a usable reply. Raised so a run stops instead of scoring garbage."""


Message = dict[str, str]  # {"role": "user" | "agent", "content": ...}, the roles the benchmark grader expects
ChatMessage = dict[str, Any]  # an OpenAI chat-completions message, used by the tool-calling arms


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # the JSON text exactly as the model produced it, which may not parse


@dataclass(frozen=True)
class Turn:
    """One model reply in the tool-calling protocol."""

    text: str = ""
    calls: tuple[ToolCall, ...] = ()

    def message(self) -> ChatMessage:
        """The reply as the assistant message that goes back into the conversation."""
        message: ChatMessage = {"role": "assistant", "content": self.text or None}
        if self.calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.calls
            ]
        return message


def tool_result(call: ToolCall, content: str) -> ChatMessage:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


class Llm(Protocol):
    def complete(self, history: Sequence[Message]) -> str: ...

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> Turn: ...


class ScriptedLlm:
    """Replays fixed replies in order and records every conversation it was shown.

    A text reply answers `complete`; a Turn answers `chat`. A reply of the wrong kind is a broken test script.
    """

    def __init__(self, replies: Sequence[str | Turn]) -> None:
        self._replies = list(replies)
        self.seen: list[list[dict[str, Any]]] = []

    def _next(self, conversation: Sequence[dict[str, Any]]) -> str | Turn:
        self.seen.append([dict(m) for m in conversation])
        if not self._replies:
            raise AssertionError("ScriptedLlm ran out of replies")
        return self._replies.pop(0)

    def complete(self, history: Sequence[Message]) -> str:
        reply = self._next(history)
        if not isinstance(reply, str):
            raise AssertionError("ScriptedLlm was asked for text but the next reply is a Turn")
        return reply

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> Turn:
        reply = self._next(messages)
        if not isinstance(reply, Turn):
            raise AssertionError("ScriptedLlm was asked for a Turn but the next reply is text")
        return reply


def _answer_text(content: Any) -> str:
    """The visible reply. Reasoning models may put their thinking before a closing think tag, which is not an answer."""
    return str(content or "").rsplit("</think>", 1)[-1].strip()


class OpenAiCompatibleLlm:
    """Chat-completions client. The key is read from a file or an environment variable and is never logged.

    A rate limit, a server error or a dropped connection is retried with a wait (Retry-After when given); after
    RETRIES attempts, or on any other error, it raises LlmError and the run stops. Runs resume, so stopping is safe.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        key_file: Path | None = None,
        key_env: str = "NEBIUS_API_KEY",
        temperature: float = 0.0,
        top_p: float | None = None,
        max_tokens: int | None = None,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = key_file.read_text().strip() if key_file is not None else os.environ.get(key_env, "")
        if not key:
            raise ValueError("no API key: pass key_file or set the environment variable")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._sampling: dict[str, float] = {"temperature": temperature}
        if top_p is not None:
            self._sampling["top_p"] = top_p
        if max_tokens is not None:
            self._sampling["max_tokens"] = max_tokens
        self._headers = {"Authorization": f"Bearer {key}"}
        self._http = http or httpx.Client(timeout=180.0)
        self._sleep = sleep

    def _post(self, request: dict[str, Any]) -> httpx.Response:
        body = {"model": self._model, **self._sampling, **request}
        for attempt in range(1, RETRIES + 1):
            try:
                response = self._http.post(self._url, headers=self._headers, json=body)
            except httpx.TransportError as exc:
                failure, wait = f"{type(exc).__name__}", 2.0**attempt
            else:
                if response.status_code < 400:
                    return response
                if response.status_code != 429 and response.status_code < 500:
                    raise LlmError(f"HTTP {response.status_code}: {response.text[:300]}")
                failure = f"HTTP {response.status_code}"
                try:
                    wait = float(response.headers["Retry-After"])
                except (KeyError, ValueError):
                    wait = 2.0**attempt
            if attempt == RETRIES:
                raise LlmError(f"{failure} after {RETRIES} attempts")
            self._sleep(min(wait, MAX_WAIT_S))
        raise AssertionError("unreachable")

    def _reply(self, request: dict[str, Any]) -> dict[str, Any]:
        body = cast(dict[str, Any], self._post(request).json())
        choices = body.get("choices")
        if not choices:
            raise LlmError(f"reply has no choices: {json.dumps(body.get('error', body))[:300]}")
        return cast(dict[str, Any], choices[0]["message"])

    def complete(self, history: Sequence[Message]) -> str:
        messages = [{"role": "assistant" if m["role"] == "agent" else "user", "content": m["content"]} for m in history]
        return _answer_text(self._reply({"messages": messages}).get("content"))

    def chat(self, messages: Sequence[ChatMessage], tools: Sequence[dict[str, Any]]) -> Turn:
        reply = self._reply({"messages": list(messages), "tools": list(tools)})
        calls: list[ToolCall] = []
        for i, raw in enumerate(cast(list[dict[str, Any]], reply.get("tool_calls") or [])):
            function = cast(dict[str, Any], raw["function"])
            arguments = function.get("arguments")
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or f"call_{i}"),  # some providers omit ids, but tool results need one
                    name=str(function["name"]),
                    arguments=arguments if isinstance(arguments, str) else json.dumps(arguments or {}),
                )
            )
        return Turn(text=_answer_text(reply.get("content")), calls=tuple(calls))
