"""The tool-calling agent (arms T and TG): a MedAgentBench v2-style design run in the benchmark's environment.

The model works through native tool calls. Every FHIR call and the final answer are also written into `history` as
the reference protocol's text actions (GET url, POST url + JSON, FINISH([...])), which is what the benchmark grader
reads. So the grader scores these arms exactly as it scores the text arms, and a create call counts as a POST attempt
whether or not a gate accepted it. Text the model writes between calls stays in `transcript` only: the grader's
"POST" text check stands in for a write attempt, and in this protocol a write attempt is a create call.

As in the reference loop, writes are never sent to the server; an accepted write is only recorded in `history`.

Searches show every match, newest first and without FHIR boilerplate (medgate.results). At finish, an answer that is
not a list of plain values (see answer_problems) gets one nudge to resend; the next finish is accepted as it stands, so
the check can never stop a task. Nudges count as format retries.

With `cfg.finish_review` (arm WATCH) the first accepted finish also gets one review (see REVIEW): the model is shown
its own orders and asked to check its decision against the protocol text. It never says that an order is missing, and
the next finish is accepted as it stands. The review is not a format retry and adds REVIEW_ROUNDS to the round limit,
so it cannot push a run that would have finished into the limit.
"""

import json
import re
from typing import Any, cast

from medgate import calculator, gates, results
from medgate.fhir import FhirClient
from medgate.gates import FORMAT_ONLY, GateConfig
from medgate.llm import ChatMessage, Llm, ToolCall, tool_result
from medgate.loop import Status, TaskResult
from medgate.protocol import GET_ERROR, GET_RESPONSE, MAX_ROUNDS, POST_ACCEPTED, POST_INVALID
from medgate.tools import FhirTool, fhir_tools, search_url, tool_definitions

REVIEW_ROUNDS = 6  # per review: the reply, a prose-only reminder round, and the finish that follows; at most two

REVIEW = (
    "Before you finish, check your decision against the protocol text. Quote the sentence of the protocol that covers "
    "this result, or say that no sentence does. Compare the result with that sentence's limits exactly as written, and "
    "check any condition the sentence names against the record. Say what the sentence requires, including the timing "
    "and dose or duration it states, and compare that with the orders you created, listed below. If they match, call "
    "finish again unchanged. If something is missing or wrong, fix or create it, then call finish. Creating no order "
    "is correct if the protocol requires none."
)

RE_REVIEW = (
    "You created or changed orders after the review. Check the whole list below once more against the protocol "
    "sentence: does it call for any order that is not in the list, such as a paired recheck, a second test or a "
    "second drug? Create what is missing, then call finish. If the list is complete, call finish again unchanged."
)

FIELD_CHECK = (
    "Then check each order field by field against that sentence: the drug or test code, the route, the dose with its "
    "unit, the rate or duration, how often it is given, the priority and the time. Every item the sentence states "
    "must appear in the order; one left out is an error even if the order looks complete."
)


def review_message(orders: list[dict[str, Any]], field_check: bool = False, again: bool = False) -> str:
    """The review text followed by the orders the agent has created so far, one JSON object per line."""
    listed = (
        "Orders you created:\n" + "\n".join(json.dumps(o) for o in orders) if orders else "You have created no orders."
    )
    return f"{RE_REVIEW if again else REVIEW}{' ' + FIELD_CHECK if field_check else ''}\n\n{listed}"


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_NUMBER_WITH_UNIT = re.compile(r"-?\d+(?:\.\d+)?\s*[A-Za-z%µ][\w/%µ^.-]*")

SYSTEM_PROMPT = """\
You are a clinical assistant working in an electronic health record through the FHIR tools provided. Everything you \
need is in the record or in the task. Do not ask the user anything.

How to work:
1. Before your first tool call, write a short plan. Say in your own words what the task asks for, list every \
condition in it, and work out which actions depend on which condition. An action attached to a conditional order \
(for example "also pair this order with ...") depends on the same condition unless the task says it applies anyway.
2. Read before you act. Create a record only when the task asks for it and every condition for it holds in data you \
retrieved. If a condition does not hold, do not create anything. When an order follows from a record you retrieved, \
cite it in the order's reasonReference, for example [{"reference": "Observation/325493"}].
3. A search returns every match, newest first, as one compact line per record after a line saying how many there \
are. If you need records older than those shown, add a date filter such as le2023-01-01 or \
ge2023-11-12T10:15:00+00:00, or set _sort to date for oldest first. Use the exact codes the task gives you.
4. Use the calculator for every calculation, including averages, doses and differences between dates. Use the \
current time stated in the task for anything dated now.
5. When the task is done, call finish with the answer list. Give exactly the values the question asks for, in the \
order it asks. Numbers must be numbers, not strings, and without units. Copy dates and times exactly as they appear \
in the record. If the task says what to answer when data is missing, answer exactly that. If the task only asks you \
to do something and asks no question, finish with [].
   Good: finish(answer=[-1]), finish(answer=["S1234567"]), finish(answer=[4.2]), \
finish(answer=[6.1, "2023-01-05T09:30:00+00:00"])
   Bad: finish(answer=["4.2"]), finish(answer=["4.2 mg/dL"]), finish(answer=[4.2, "January 5, 2023"])
"""
REMINDER = "Continue by calling a tool. When the task is complete, call finish with your answer."


def _row_limit(value: Any) -> int | None:
    try:
        return max(1, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def answer_problems(answer: list[Any]) -> list[str]:
    """Why an answer is not a list of plain values: an object or list inside it, a sentence (four or more words),
    or a number written as text or carrying a unit. These were 96 of GPT-4.1's 125 failures on the reference loop
    (docs/GPT41_BASELINE.md). Short text such as "Patient not found", dates and MRNs pass.
    """
    problems: list[str] = []
    for value in answer:
        if isinstance(value, dict | list):
            problems.append(f"{json.dumps(value)[:80]} is an object or list; give plain values")
            continue
        text = value.strip() if isinstance(value, str) else None
        if text is None:
            continue
        if len(text.split()) >= 4:
            problems.append(f"{text[:80]!r} is a sentence; give only the values asked for")
        elif _NUMBER.fullmatch(text):
            problems.append(f"{value!r} is a number written as text")
        elif _NUMBER_WITH_UNIT.fullmatch(text):
            problems.append(f"{value!r} carries a unit; give the number alone")
    return problems


class _Task:
    """One task's environment: runs tool calls, keeps the grader's view in sync, and counts what the gates did."""

    def __init__(
        self,
        case: dict[str, Any],
        functions: list[dict[str, Any]],
        fhir: FhirClient,
        cfg: GateConfig,
        result: TaskResult,
    ) -> None:
        self._functions = functions
        self._tools = fhir_tools(functions)
        self._fhir = fhir
        self._cfg = cfg
        self._result = result
        self._evidence = f"{case['context']}\n{case['instruction']}"
        self._nudged = False
        self._reviewed = False
        self._reviewed_orders = 0  # orders accepted when the review was shown
        self._re_reviewed = False
        self._accepted: list[dict[str, Any]] = []  # payloads of the writes accepted so far, shown back at the review
        self.definitions = tool_definitions(self._tools)

    def _record(self, agent: str, environment: str) -> None:
        self._result.history += [{"role": "agent", "content": agent}, {"role": "user", "content": environment}]

    def execute(self, call: ToolCall) -> str:
        """Run one tool call and return what the model is told. A finish call completes the result."""
        try:
            arguments: Any = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            arguments = None
        if call.name == "finish":
            return self._finish(arguments)
        if call.name == "calculator":
            return self._calculate(arguments)
        tool = self._tools.get(call.name)
        if tool is None:
            return f"Error: there is no tool named {call.name!r}."
        if tool.method == "GET":
            return self._search(tool, arguments)
        return self._create(tool, arguments, call.arguments)

    def _search(self, tool: FhirTool, arguments: Any) -> str:
        if not isinstance(arguments, dict):
            return "Error: the arguments must be a JSON object."
        parameters = cast(dict[str, Any], arguments)
        url = search_url(tool, parameters, self._fhir.base)
        problems = gates.read_problems(parameters, self._evidence) if self._cfg.require_evidence else []
        if problems:
            self._result.rejected_reads += 1
            reply = gates.read_rejection_message(problems)
            self._record(f"GET {url}", reply)
            return reply
        fetched = self._fhir.get(f"{url}&_format=json")
        if fetched.error is not None:
            reply = GET_ERROR.format(error=fetched.error)
            self._record(f"GET {url}", reply)
            return reply
        newest_first = parameters.get("_sort") != "date"
        data = results.render(str(fetched.data), newest_first, _row_limit(parameters.get("_count")))
        self._evidence += f"\n{data}"
        self._record(f"GET {url}", GET_RESPONSE.format(data=data))
        return data

    def _create(self, tool: FhirTool, arguments: Any, raw: str) -> str:
        url = f"{self._fhir.base}{tool.resource}"
        if not isinstance(arguments, dict):
            self._record(f"POST {url}\n{raw}", POST_INVALID)
            return f"{POST_INVALID}: the arguments must be a JSON object."
        # The tool targets one resource type, so it fills resourceType when the model leaves it out.
        payload = {"resourceType": tool.resource, **cast(dict[str, Any], arguments)}
        problems = gates.write_problems(url, payload, self._functions, self._cfg, self._evidence)
        if problems:
            self._result.rejected_posts += 1
            reply = gates.rejection_message(problems)
            self._record(f"POST {url}\n{json.dumps(payload)}", reply)
            return reply
        self._record(f"POST {url}\n{json.dumps(payload)}", POST_ACCEPTED)
        self._accepted.append(payload)
        return "Accepted: the write is recorded."  # not "created": no write reaches the server without review

    def _calculate(self, arguments: Any) -> str:
        expression = cast(dict[str, Any], arguments).get("expression") if isinstance(arguments, dict) else None
        if not isinstance(expression, str):
            return 'Error: call the calculator with {"expression": "..."}.'
        try:
            return json.dumps(calculator.evaluate(expression))
        except calculator.CalculatorError as exc:
            return f"Error: {exc}"

    def _finish(self, arguments: Any) -> str:
        answer = cast(dict[str, Any], arguments).get("answer") if isinstance(arguments, dict) else None
        if not isinstance(answer, list):
            return 'Error: call finish with {"answer": [...]}, a list of values.'
        if not self._nudged and (problems := answer_problems(cast(list[Any], answer))):
            self._nudged = True
            self._result.format_retries += 1
            return f"Check the answer: {'; '.join(problems)}. Call finish again, corrected or unchanged."
        if self._cfg.finish_review and not self._reviewed:
            self._reviewed = True
            self._reviewed_orders = len(self._accepted)
            return review_message(self._accepted, self._cfg.field_check)
        if self._cfg.finish_review and not self._re_reviewed and len(self._accepted) != self._reviewed_orders:
            self._re_reviewed = True  # an order written after the review is checked once, as the first ones were
            return review_message(self._accepted, self._cfg.field_check, again=True)
        self._result.status, self._result.result = Status.COMPLETED, json.dumps(answer)
        self._result.history.append({"role": "agent", "content": f"FINISH({self._result.result})"})
        return "Finished."


def run_tool_task(
    case: dict[str, Any],
    functions: list[dict[str, Any]],
    llm: Llm,
    fhir: FhirClient,
    cfg: GateConfig = FORMAT_ONLY,
    max_rounds: int = MAX_ROUNDS,
) -> TaskResult:
    """Run one task with native tool calls. Each model call is one round, as in the benchmark's round limit."""
    messages: list[ChatMessage] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Context: {case['context']}\nQuestion: {case['instruction']}"},
    ]
    result = TaskResult(history=[], status=Status.LIMIT_REACHED, transcript=messages)
    task = _Task(case, functions, fhir, cfg, result)
    for _ in range(max_rounds + (REVIEW_ROUNDS if cfg.finish_review else 0)):
        turn = llm.chat(messages, task.definitions)
        messages.append(turn.message())
        if not turn.calls:
            if not cfg.format_retry:
                result.status = Status.INVALID_ACTION
                return result
            result.format_retries += 1
            messages.append({"role": "user", "content": REMINDER})
            continue
        for call in turn.calls:
            messages.append(tool_result(call, task.execute(call)))
            if result.status is Status.COMPLETED:
                return result
    return result
