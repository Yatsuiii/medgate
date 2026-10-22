"""MedAgentBench interaction protocol, reproduced from stanfordmlgroup/MedAgentBench (MIT license).

The benchmark grader reads the conversation history, so the wording and the roles here must match the
reference exactly: messages come from "user" (task and environment) and "agent" (the model).
"""

import json
from dataclasses import dataclass
from typing import Any

FHIR_BASE = "http://localhost:8080/fhir/"
MAX_ROUNDS = 8

PROMPT = (
    "You are an expert in using FHIR functions to assist medical professionals. You are given a question and a set "
    "of possible functions. Based on the question, you will need to make one or more function/tool calls to achieve "
    "the purpose.\n\n1. If you decide to invoke a GET function, you MUST put it in the format of\nGET "
    "url?param_name1=param_value1&param_name2=param_value2...\n\n2. If you decide to invoke a POST function, you "
    "MUST put it in the format of\nPOST url\n[your payload data in JSON format]\n\n3. If you have got answers for "
    "all the questions and finished all the requested tasks, you MUST call to finish the conversation in the format "
    "of (make sure the list is JSON loadable.)\nFINISH([answer1, answer2, ...])\n\nYour response must be in the "
    "format of one of the three cases, and you can call only one function each time. You SHOULD NOT include any "
    "other text in the response.\n\nHere is a list of functions in JSON format that you can invoke. Note that you "
    "should use {api_base} as the api_base.\n{functions}\n\nContext: {context}\nQuestion: {question}"
)
_FINISH_HINT = "Please call FINISH if you have got answers for all the questions and finished all the requested tasks"
GET_RESPONSE = "Here is the response from the GET request:\n{data}. " + _FINISH_HINT
GET_ERROR = "Error in sending the GET request: {error}"
POST_INVALID = "Invalid POST request"
POST_ACCEPTED = "POST request accepted and executed successfully. " + _FINISH_HINT


@dataclass(frozen=True)
class Get:
    url: str


@dataclass(frozen=True)
class Post:
    url: str
    payload: Any  # None when the body is not valid JSON; the reference accepts any other JSON value


@dataclass(frozen=True)
class Finish:
    answer: str  # the text inside FINISH( ... ) exactly as the reference slices it


@dataclass(frozen=True)
class Invalid:
    text: str


Action = Get | Post | Finish | Invalid


def parse_reply(reply: str) -> Action:
    """Classify a model reply the way the reference loop does, including its stripping of code fences."""
    text = reply.strip().replace("```tool_code", "").replace("```", "").strip()
    if text.startswith("GET"):
        return Get(text[3:].strip() + "&_format=json")
    if text.startswith("POST"):
        lines = text.split("\n")
        try:
            payload = json.loads("\n".join(lines[1:]))
        except Exception:  # noqa: BLE001 - the reference treats any parse failure as an invalid POST
            payload = None
        return Post(lines[0][4:].strip(), payload)
    if text.startswith("FINISH("):
        return Finish(text[len("FINISH(") : -1])
    return Invalid(text)


def build_prompt(case: dict[str, Any], functions: list[dict[str, Any]], api_base: str = FHIR_BASE) -> str:
    return PROMPT.format(
        api_base=api_base,
        functions=json.dumps(functions),
        context=case["context"],
        question=case["instruction"],
    )
