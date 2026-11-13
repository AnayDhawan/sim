"""Limits ledger and fidelity. The ledger is reported beside every score and is NEVER multiplied into it.

fidelity = 100 * mean(status_value over the ledger rows relevant to that purpose)
status_value: broken 0, partly 0.5, matchable 1. The relevance matrix is a DRAFT (ledger.yaml, provisional: true).
"""

from __future__ import annotations

from typing import Any


def relevant_rows(ledger: dict[str, Any], body: str, profile: str) -> list[dict[str, Any]]:
    rows = [r for r in ledger["rows"] if body in r["bodies"]]
    rel = ledger["relevance"][profile]["rows"]
    return rows if rel == "all" else [r for r in rows if r["id"] in rel]


def fidelity(ledger: dict[str, Any], body: str, profile: str) -> dict[str, Any]:
    rows = relevant_rows(ledger, body, profile)
    vals = ledger["status_value"]
    score = 100.0 * sum(vals[r["status"]] for r in rows) / len(rows) if rows else None
    return {"body": body, "profile": profile, "fidelity": score, "n_rows": len(rows),
            "rows": [{"id": r["id"], "status": r["status"], "provisional": bool(r.get("provisional", False))}
                     for r in rows],
            "relevance_provisional": bool(ledger.get("relevance_provisional", True)),
            "reason": ledger["relevance"][profile]["reason"],
            "note": "Reported beside the score. Never multiplied into it."}


def ledger_table(ledger: dict[str, Any], body: str) -> list[dict[str, Any]]:
    return [{k: r.get(k) for k in ("id", "property", "target", "earth", "status", "source", "provisional")}
            for r in ledger["rows"] if body in r["bodies"]]
