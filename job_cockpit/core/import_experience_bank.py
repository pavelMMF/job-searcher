from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MASTER_RESUME = ROOT / "config" / "master_resume.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or "").strip(),
        "source": str(item.get("source") or "").strip(),
        "role_period": str(item.get("role_period") or "").strip(),
        "tags": normalize_list(item.get("tags")),
        "skills": normalize_list(item.get("skills")),
        "bullets": normalize_list(item.get("bullets")),
        "notes": str(item.get("notes") or "").strip(),
    }


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def merge_bank(master: dict[str, Any], incoming: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    existing = master.get("experience_bank", [])
    if not isinstance(existing, list):
        existing = []
    by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for raw in existing:
        if not isinstance(raw, dict):
            continue
        item = normalize_item(raw)
        item_id = item.get("id") or f"existing_{len(ordered_ids) + 1}"
        item["id"] = item_id
        if item_id not in by_id:
            ordered_ids.append(item_id)
        by_id[item_id] = item
    changed = 0
    for raw in incoming:
        item = normalize_item(raw)
        if not item["id"]:
            item["id"] = slug_id(item)
        if not item["bullets"]:
            continue
        if item["id"] not in by_id:
            ordered_ids.append(item["id"])
        if by_id.get(item["id"]) != item:
            changed += 1
        by_id[item["id"]] = item
    master["experience_bank"] = [by_id[item_id] for item_id in ordered_ids if item_id in by_id]
    return master, changed


def slug_id(item: dict[str, Any]) -> str:
    source = item.get("source") or "experience"
    tags = "_".join(item.get("tags", [])[:3])
    raw = "_".join(part for part in [source, tags] if part)
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw)
    clean = "_".join(part for part in clean.split("_") if part)
    return clean[:80] or "experience_item"


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge additional real experience into master_resume.json.")
    parser.add_argument("bank_json", help="Path to a JSON list of experience-bank items.")
    parser.add_argument("--master", default=str(MASTER_RESUME), help="Path to master_resume.json.")
    args = parser.parse_args()

    bank_path = Path(args.bank_json)
    master_path = Path(args.master)
    incoming = load_json(bank_path)
    if not isinstance(incoming, list) or not all(isinstance(item, dict) for item in incoming):
        raise SystemExit("Experience bank must be a JSON list of objects.")
    master = load_json(master_path)
    if not isinstance(master, dict):
        raise SystemExit("master_resume.json must be a JSON object.")
    merged, changed = merge_bank(master, incoming)
    master_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged {changed} experience-bank item(s) into {master_path}.")


if __name__ == "__main__":
    main()
