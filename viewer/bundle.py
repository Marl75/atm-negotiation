"""Bundle logs/*.jsonl and eval/*/ into viewer/*_data.js so the pages open offline with a double-click.

Usage: python3 viewer/bundle.py   (re-run after new negotiations or evals; index.html also accepts dropped .jsonl)

Everything is passed through as-is: the pages read whatever schema the logs and eval files have.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
EVAL_DIR = ROOT / "eval"
OUT_DIR = Path(__file__).resolve().parent


def bundle_logs() -> list[dict]:
    logs = []
    for path in sorted(LOG_DIR.glob("*.jsonl")):
        lines = []
        for raw in path.read_text().splitlines():
            if raw.strip():
                try:
                    lines.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass  # half-written log: keep the lines that parse
        if lines:
            logs.append({"file": path.name, "lines": lines})
    return logs


def _value(raw: str):
    """summary.md values are Python reprs (dicts, None, floats) or plain text like '20/20'."""
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def bundle_evals() -> list[dict]:
    runs = []
    for d in sorted(p for p in EVAL_DIR.glob("*") if p.is_dir()):
        summary, title = {}, ""
        if (d / "summary.md").exists():
            for line in (d / "summary.md").read_text().splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                m = re.match(r"- \*\*(.+?)\*\*: (.*)$", line)
                if m:
                    summary[m[1]] = _value(m[2])
        rows = []
        if (d / "results.csv").exists():
            with (d / "results.csv").open(newline="") as f:
                rows = list(csv.DictReader(f))
        if summary or rows:
            runs.append({"stamp": d.name, "title": title, "summary": summary, "rows": rows})
    return runs


def main() -> None:
    logs, evals = bundle_logs(), bundle_evals()
    (OUT_DIR / "logs_data.js").write_text("window.ATM_LOGS = " + json.dumps(logs, ensure_ascii=False) + ";\n")
    (OUT_DIR / "eval_data.js").write_text("window.ATM_EVALS = " + json.dumps(evals, ensure_ascii=False) + ";\n")
    print(f"{len(logs)} logs -> viewer/logs_data.js, {len(evals)} eval runs -> viewer/eval_data.js")


if __name__ == "__main__":
    main()
