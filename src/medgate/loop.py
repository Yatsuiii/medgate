"""The agent loop. With every gate off it behaves exactly like the benchmark's reference loop."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from medgate import gates
from medgate.fhir import FhirClient
from medgate.gates import REFERENCE, GateConfig
from medgate.llm import ChatMessage, Llm, Message
from medgate.protocol import (
    GET_ERROR,
    GET_RESPONSE,
    MAX_ROUNDS,
    POST_ACCEPTED,
    POST_INVALID,
    Finish,
    Get,
    Invalid,
    build_prompt,
    parse_reply,
)


class Status(StrEnum):
    COMPLETED = "completed"
    INVALID_ACTION = "agent_invalid_action"
    LIMIT_REACHED = "task_limit_reached"


@dataclass
class TaskResult:
    """Shaped like the reference TaskOutput: the grader reads `history` and `result`.

    `transcript` is the native conversation of the tool-calling arms; it stays empty for the text protocol, where
    `history` is the whole conversation.
    """

    history: list[Message]
    status: Status
    result: str | None = None
    rejected_posts: int = 0
    format_retries: int = 0
    rejected_reads: int = 0
    transcript: list[ChatMessage] = field(default_factory=lambda: list[ChatMessage]())


def run_task(
    case: dict[str, Any],
    functions: list[dict[str, Any]],
    llm: Llm,
    fhir: FhirClient,
    cfg: GateConfig = REFERENCE,
    max_rounds: int = MAX_ROUNDS,
) -> TaskResult:
    history: list[Message] = [{"role": "user", "content": build_prompt(case, functions)}]
    evidence = f"{case['context']}\n{case['instruction']}"
    result = TaskResult(history, Status.LIMIT_REACHED)
    for _ in range(max_rounds):
        reply = llm.complete(history)
        history.append({"role": "agent", "content": reply})
        action = parse_reply(reply)
        if isinstance(action, Finish):
            result.status, result.result = Status.COMPLETED, action.answer
            return result
        if isinstance(action, Invalid):
            if not cfg.format_retry:
                result.status = Status.INVALID_ACTION
                return result
            result.format_retries += 1
            reply_to_agent = gates.FORMAT_RETRY
        elif isinstance(action, Get):
            fetched = fhir.get(action.url)
            if fetched.error is None:
                evidence += f"\n{fetched.data}"
                reply_to_agent = GET_RESPONSE.format(data=fetched.data)
            else:
                reply_to_agent = GET_ERROR.format(error=fetched.error)
        elif action.payload is None:
            reply_to_agent = POST_INVALID
        else:
            problems = gates.write_problems(action.url, action.payload, functions, cfg, evidence)
            result.rejected_posts += bool(problems)
            reply_to_agent = gates.rejection_message(problems) if problems else POST_ACCEPTED
        history.append({"role": "user", "content": reply_to_agent})
    return result
