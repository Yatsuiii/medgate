"""Pure tests for how search results are shown to the agent: compaction, ordering, limits and the size budget."""

import json
from typing import Any

from medgate.results import MAX_CHARS, NO_RESULTS, clinical_time, compact, render

LAB = {
    "resourceType": "Observation",
    "id": "325388",
    "meta": {"versionId": "1", "lastUpdated": "2024-12-30T20:49:40.860+05:30", "source": "#btV7ngIfnC13E0pC"},
    "text": {"status": "generated", "div": "<div>K 3.6</div>"},
    "status": "final",
    "category": [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "laboratory",
                    "display": "Laboratory",
                }
            ]
        }
    ],
    "code": {"coding": [{"system": "http://loinc.org", "code": "K", "display": "K"}], "text": "K"},
    "subject": {"reference": "Patient/S3241217", "identifier": {"system": "urn:x", "value": "S3241217"}},
    "effectiveDateTime": "2023-08-01T21:10:00+00:00",
    "valueQuantity": {"value": 3.6, "unit": "mmol/L", "system": "http://unitsofmeasure.org", "code": "mmol/L"},
    "note": [{"text": "hemolyzed"}],
}


def bundle(resources: list[dict[str, Any]], **extra: Any) -> str:
    return json.dumps({"resourceType": "Bundle", "entry": [{"resource": r} for r in resources], **extra})


def lines_of(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.split("\n")[1:]]


def test_compact_keeps_the_data_and_drops_the_boilerplate() -> None:
    assert compact(LAB) == {
        "resourceType": "Observation",
        "id": "325388",
        "status": "final",
        "category": ["laboratory (Laboratory)"],
        "code": "K",
        "subject": "Patient/S3241217",
        "effectiveDateTime": "2023-08-01T21:10:00+00:00",
        "valueQuantity": {"value": 3.6, "unit": "mmol/L"},
        "note": [{"text": "hemolyzed"}],
    }


def test_compact_keeps_systems_that_are_not_urls_and_codes_that_differ_from_the_text() -> None:
    contact = {"telecom": [{"system": "phone", "value": "555-0100"}]}
    concept = {"code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}], "text": "A1C"}}
    assert compact(contact) == contact
    assert compact(concept) == {"code": {"coding": ["4548-4"], "text": "A1C"}}


def test_clinical_time_takes_the_first_time_a_resource_has() -> None:
    assert str(clinical_time({"performedPeriod": {"start": "2023-01-01"}, "issued": "2024-01-01"})) == (
        "2023-01-01 00:00:00+00:00"
    )
    assert clinical_time({"birthDate": "1932-12-29"}) is None


def test_render_orders_by_clinical_time_and_puts_undated_records_last() -> None:
    resources = [
        {"id": "a", "effectiveDateTime": "2023-01-01T00:00:00+00:00"},
        {"id": "undated"},
        {"id": "b", "authoredOn": "2023-06-01T00:00:00+00:00"},
    ]
    newest = render(bundle(resources))
    assert newest.split("\n")[0] == "3 results, newest first."
    assert [r["id"] for r in lines_of(newest)] == ["b", "a", "undated"]
    assert [r["id"] for r in lines_of(render(bundle(resources), newest_first=False))] == ["a", "b", "undated"]


def test_render_limit_shows_only_that_many_and_says_so() -> None:
    resources = [{"id": str(i), "effectiveDateTime": f"2023-01-{i + 1:02d}"} for i in range(5)]
    text = render(bundle(resources), limit=2)
    assert text.startswith("5 results, newest first; showing the first 2.") and len(lines_of(text)) == 2


def test_render_keeps_the_newest_records_within_the_size_budget() -> None:
    resources = [
        {"id": f"r{i}", "effectiveDateTime": f"2023-01-01T00:{i % 60:02d}:{i // 60:02d}", "pad": "x" * 500}
        for i in range(300)
    ]
    text = render(bundle(resources))
    shown = lines_of(text)
    assert len(text) <= MAX_CHARS + 200 and 0 < len(shown) < 300
    assert text.split("\n")[0].startswith(f"300 results, newest first; showing the first {len(shown)}.")
    newest = max(resources, key=lambda r: r["effectiveDateTime"])
    assert shown[0]["id"] == newest["id"]


def test_render_says_when_the_server_had_more_than_it_sent() -> None:
    text = render(bundle([{"id": "a"}], link=[{"relation": "next", "url": "http://x"}]))
    assert text.split("\n")[0] == "1 result. More matched than the 1 fetched."


def test_render_reports_an_empty_search_plainly_and_passes_other_text_through() -> None:
    assert render(bundle([])) == NO_RESULTS and "try it before concluding nothing is recorded" in NO_RESULTS
    assert render("not json") == "not json"
    assert render(json.dumps({"resourceType": "OperationOutcome"})) == '{"resourceType": "OperationOutcome"}'
