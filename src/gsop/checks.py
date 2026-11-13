"""Status-line reporter for gates and checks. Recycled from the IRIS scripts/gatelib.py.

Statuses: PASS, FAIL, PASS* / FAIL* (depends on a provisional value), PENDING (data not produced yet),
INFO (reported number, no threshold), WARN.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console

from .provenance import write_json

console = Console(highlight=False)


@dataclass
class Line:
    name: str
    status: str
    detail: str = ""


def judge(ok: bool, provisional: bool = False) -> str:
    return ("PASS" if ok else "FAIL") + ("*" if provisional else "")


class Report:
    def __init__(self, name: str, quiet: bool = False) -> None:
        self.name = name
        self.quiet = quiet
        self.lines: list[Line] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.lines.append(Line(name, status, detail))
        if not self.quiet:
            console.print(f"[{status}] {name}" + (f"  ({detail})" if detail else ""))

    def check(self, name: str, ok: bool, detail: str = "", provisional: bool = False) -> None:
        self.add(name, judge(ok, provisional), detail)

    @property
    def failed(self) -> list[Line]:
        return [ln for ln in self.lines if ln.status.startswith("FAIL")]

    def finish(self, out: Path | str | None = None) -> int:
        if out is not None:
            write_json(out, {"report": self.name, "lines": [asdict(ln) for ln in self.lines]})
        counts = {s: sum(ln.status == s for ln in self.lines)
                  for s in ("PASS", "PASS*", "FAIL", "FAIL*", "PENDING", "INFO", "WARN")}
        if not self.quiet:
            console.print(f"{self.name.upper()}: {'FAIL' if self.failed else 'PASS (no FAIL lines)'}; "
                          + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
        return 1 if self.failed else 0
