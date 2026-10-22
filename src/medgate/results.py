"""How search results are shown to the tool-calling agent: every match, newest first, without FHIR boilerplate.

The server returns verbose bundles in no particular order. An agent reading raw pages can miss the newest value, which
is what most clinical questions ask about, and spends most of its context on metadata. Here a bundle becomes a count
line followed by one compact JSON line per resource, sorted by the time the resource is about, cut to a size budget
with a note saying how to see the rest. Values keep their types and times keep their exact text, so an answer can be
copied from a line as it stands.
"""

import json
from datetime import UTC, datetime
from typing import Any, cast

MAX_CHARS = 60_000  # about 230 compact observations
CUT_NOTE = "Narrow the search with a date filter, _sort or _count."
# GPT-4.1 failed 30 of 300 tasks by searching a code that had no results and concluding nothing was recorded
# (docs/GPT41_BASELINE.md), so an empty search says what to try first.
NO_RESULTS = (
    "0 results. If the task gives another code or parameter for this, try it before concluding nothing is recorded."
)

# The time a resource is about, in order of preference; the first one present orders the results.
_CLINICAL_TIMES = (
    "effectiveDateTime",
    "effectiveInstant",
    "effectivePeriod",
    "performedDateTime",
    "performedPeriod",
    "occurrenceDateTime",
    "authoredOn",
    "recordedDate",
    "onsetDateTime",
    "issued",
    "date",
)
_BOILERPLATE = frozenset({"meta", "fullUrl", "search", "link"})
_CODING_KEYS = frozenset({"system", "code", "display", "version", "userSelected"})
_EMPTY: tuple[Any, ...] = (None, "", [], {})


def _moment(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = cast(dict[str, Any], value).get("start")  # a Period
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def clinical_time(resource: dict[str, Any]) -> datetime | None:
    return next((_moment(resource[key]) for key in _CLINICAL_TIMES if key in resource), None)


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://", "urn:"))


def _collapse(fields: dict[str, Any]) -> Any:
    """A CodeableConcept whose text repeats its one coding becomes the coding; a code that repeats the unit goes."""
    codings = fields.get("coding")
    if isinstance(codings, list) and len(cast(list[Any], codings)) == 1 and set(fields) <= {"coding", "text"}:
        coding = cast(list[Any], codings)[0]
        text = fields.get("text")
        if text is None or text == coding:
            return coding
    if "unit" in fields and fields.get("code") == fields["unit"]:
        return {key: value for key, value in fields.items() if key != "code"}
    return fields


def compact(node: Any) -> Any:
    """`node` without boilerplate. Codings and References become strings; meta, narrative and URL systems go."""
    if isinstance(node, list):
        items = [compact(item) for item in cast(list[Any], node)]
        return [item for item in items if item not in _EMPTY]
    if not isinstance(node, dict):
        return node
    fields = cast(dict[str, Any], node)
    if "div" in fields:  # a narrative: generated HTML repeating the data
        return None
    if isinstance(reference := fields.get("reference"), str):
        display = fields.get("display")
        return f"{reference} ({display})" if display else reference
    if isinstance(fields.get("code"), str) and set(fields) <= _CODING_KEYS:
        code, display = fields["code"], fields.get("display")
        return f"{code} ({display})" if display and display != code else code
    kept = {
        key: compact(value)
        for key, value in fields.items()
        if key not in _BOILERPLATE and not (key == "system" and _is_url(value))
    }
    return _collapse({key: value for key, value in kept.items() if value not in _EMPTY})


def clip(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return f"{text[:MAX_CHARS]}\n[cut: showing {MAX_CHARS} of {len(text)} characters. {CUT_NOTE}]"


def render(raw: str, newest_first: bool = True, limit: int | None = None) -> str:
    """What the agent sees for a search. Anything that is not a FHIR bundle is shown as the server sent it."""
    try:
        bundle: Any = json.loads(raw)
    except json.JSONDecodeError:
        return clip(raw)
    if not isinstance(bundle, dict) or cast(dict[str, Any], bundle).get("resourceType") != "Bundle":
        return clip(raw)
    entries = cast(list[dict[str, Any]], cast(dict[str, Any], bundle).get("entry", []))
    resources = [cast(dict[str, Any], entry["resource"]) for entry in entries if "resource" in entry]
    if not resources:
        return NO_RESULTS
    timed = [(clinical_time(r), r) for r in resources]
    dated = sorted(((t, r) for t, r in timed if t is not None), key=lambda pair: pair[0], reverse=newest_first)
    ordered = [r for _, r in dated] + [r for t, r in timed if t is None]
    lines = [json.dumps(compact(r), separators=(",", ":"), ensure_ascii=False) for r in ordered][:limit]
    shown, size = 0, 0
    while shown < len(lines) and size + len(lines[shown]) + 1 <= MAX_CHARS:
        size += len(lines[shown]) + 1
        shown += 1
    header = f"{len(resources)} result{'' if len(resources) == 1 else 's'}"
    if dated:
        header += ", newest first" if newest_first else ", oldest first"
    header += "." if shown == len(resources) else f"; showing the first {shown}. {CUT_NOTE}"
    links = cast(list[dict[str, Any]], cast(dict[str, Any], bundle).get("link", []))
    if any(link.get("relation") == "next" for link in links):
        header += f" More matched than the {len(resources)} fetched."
    return "\n".join([header, *lines[:shown]])
