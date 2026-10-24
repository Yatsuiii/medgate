# ruff: noqa: E501 - the page text embedded below has long lines
"""Build the hosted demo page: a read-only snapshot of one real scan of the demo ward.

One scan on the live model (Nemotron on Nebius), taken as it comes: no selection among scans. The page is the review
screen with its three API calls answered from the saved scan, so nothing is running behind it and nothing can be
written. A banner says so. The snapshot is for looking at; running the screen yourself (README) writes real orders.

Usage, from the repository root with the FHIR server up (the cited records are read from it) and a key file:
    uv run python -I demo/build_static.py --model nvidia/nemotron-3-super-120b-a12b \
        --base-url https://api.tokenfactory.nebius.com/v1/ --key-file ~/.nebius_key --out docs/demo
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from medgate.fhir import FhirClient
from medgate.llm import OpenAiCompatibleLlm
from medgate.tasks import watch_functions
from medgate.watch import load_ward
from medgate.web import PAGE, ReviewApp

BANNER = """<div id="snapshot" style="background:#fff4d6;color:#4a3b00;border-bottom:2px solid #d9b44a;padding:10px 16px;
font:14px/1.45 system-ui,sans-serif">
<strong>Recorded scan, read-only.</strong> This page shows one real scan of the demo ward by __MODEL__ on Nebius Token
Factory, recorded __WHEN__. Nothing is running behind it, no model is called when you click, and Approve writes
nothing. To run the screen on your own server and write orders, follow the README. Synthetic patients, no clinical use.
</div>"""

STUB = """<script>
const SNAPSHOT = __SNAPSHOT__;
window.fetch = async (path, options) => {
  const reply = (status, body) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
  if (path === "/api/mode") return reply(200, SNAPSHOT.mode);
  if (path === "/api/watch") {
    const wanted = JSON.parse(options.body).patients || [];
    return reply(200, {events: SNAPSHOT.events.filter((e) => wanted.length === 0 || wanted.includes(e.patient))});
  }
  if (path === "/api/commit") return reply(409, {error: "This page is a recorded snapshot: nothing can be written here. Run the screen locally (see the README) to approve and write an order."});
  return reply(404, {error: "not available on the recorded snapshot"});
};
</script>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--key-file", type=Path, default=Path.home() / ".nebius_key")
    parser.add_argument("--ward", type=Path, default=Path("demo/ward.json"))
    parser.add_argument("--out", type=Path, default=Path("docs/demo"))
    args = parser.parse_args()
    llm = OpenAiCompatibleLlm(
        args.base_url, args.model, key_file=args.key_file, temperature=1.0, top_p=0.95, max_tokens=8192
    )
    mode: dict[str, Any] = {"replay": False, "model": args.model, "ask": {"context": "", "question": ""}}
    app = ReviewApp(lambda case: llm, FhirClient(), watch_functions(), mode, load_ward(args.ward))
    events = app.watch(None)
    snapshot = {"mode": app.describe(), "events": events}
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    page = PAGE.read_text()
    page = page.replace("<script>", STUB.replace("__SNAPSHOT__", json.dumps(snapshot)) + "\n<script>", 1)
    banner = BANNER.replace("__MODEL__", args.model).replace("__WHEN__", when)
    page = page.replace("<body>", "<body>\n" + banner, 1)
    # The ask view needs a model behind it; the snapshot has the worklist only.
    page = page.replace("</body>", '<script>document.getElementById("tab-ask").hidden = true;</script>\n</body>', 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(page)
    (args.out / "snapshot.json").write_text(json.dumps(snapshot, indent=1) + "\n")
    done = sum(e["status"] == "completed" for e in events)
    acting = sum(bool(e["proposals"]) for e in events)
    print(f"{len(events)} results, {done} completed, {acting} with orders -> {args.out}/index.html")


if __name__ == "__main__":
    main()
