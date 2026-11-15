"""Write runs/v2/STATUS_A.md. Usage: python a_status.py "<stage>" "<done>" "<next>" ["<failures>"]. Time is IST."""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
stage, done, nxt = sys.argv[1:4]
fails = sys.argv[4] if len(sys.argv) > 4 else "none"
pull = ROOT / "runs" / "v2" / "logs" / "pull_state.json"
extra = ""
if pull.exists():
    try:
        d = json.loads(pull.read_text())
        extra = f"- Earth Engine pull: {d.get('done')}/{d.get('total')} land blocks, {len(d.get('failed', []))} failed\n"
    except Exception:  # noqa: BLE001
        pass
now = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
(ROOT / "runs" / "v2" / "STATUS_A.md").write_text(
    f"# STATUS_A (ROLE A, Earth thermal layer and scoring)\n\n- updated: {now}\n- hard stop: 2026-11-15 17:00 IST\n"
    f"- stage: {stage}\n- done: {done}\n- next: {nxt}\n- failures: {fails}\n{extra}", encoding="utf-8")
