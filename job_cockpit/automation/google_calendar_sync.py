from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

from calendar_tools import build_ics  # noqa: E402
from storage import Store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export interview meetings for Google Calendar import.")
    parser.add_argument("--db", default=str(ROOT / "cockpit.db"))
    parser.add_argument("--out", default=str(ROOT / "interviews.ics"))
    args = parser.parse_args()

    store = Store(args.db)
    target = Path(args.out)
    target.write_text(build_ics(store.list_meetings()), encoding="utf-8")
    print(f"Wrote {target}")
    print("Import this .ics file into Google Calendar, or wire OAuth later with google-api-python-client.")


if __name__ == "__main__":
    main()
