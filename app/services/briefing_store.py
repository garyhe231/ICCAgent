"""
In-memory briefing store with optional JSON persistence.
Stores completed ICC runs so the dashboard can show history.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from app.config import OUTPUT_DIR

_runs: list[dict] = []


def _load_runs_from_disk() -> None:
    """Load all persisted runs from OUTPUT_DIR on startup, newest first."""
    if not os.path.isdir(OUTPUT_DIR):
        return
    files = sorted(
        [f for f in os.listdir(OUTPUT_DIR) if f.startswith("icc_briefing_") and f.endswith(".json")],
        reverse=True,
    )
    for fname in files:
        try:
            with open(os.path.join(OUTPUT_DIR, fname)) as f:
                record = json.load(f)
            # Re-parse icc_ranges in case regex has been updated
            record["icc_ranges"] = _parse_icc_ranges(record.get("content", ""))
            _runs.append(record)
        except Exception:
            pass

# Port pair labels in the order they appear in the briefing (all supported lanes)
_PORT_PAIR_PATTERNS = [
    ("China Base Ports", "PSW"),
    ("China Base Ports", "PNW"),
    ("China Base Ports", "EC"),
    ("China Base Ports", "Gulf"),
    ("SEA", "PSW"),
    ("SEA", "EC"),
    # FEWB
    ("China Base Ports", "North Europe"),
    ("China Base Ports", "Med"),
    ("SEA", "North Europe"),
    ("SEA", "Med"),
    ("NEA", "North Europe"),
]

CONFIDENCE_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _parse_icc_ranges(content: str) -> list:
    """
    Extract ICC ranges from the briefing markdown.
    Looks for patterns like: $2,050 – $2,200 / 40ft  or  $2,050 - $2,200/40ft
    near each port-pair heading.
    Returns list of dicts: {origin, destination, range_low, range_high, range_str, confidence}
    """
    results = []
    # Split into sections by port-pair headings (### CHINA BASE PORTS → PSW etc.)
    # Try to find each port pair section
    for origin, dest in _PORT_PAIR_PATTERNS:
        # Match headings like "### China Base Ports → PSW" (unicode → or ASCII ->)
        heading_pat = re.compile(
            rf"#+ *[^\w]*{origin}[\s\u2192\->/]+{dest}",
            re.IGNORECASE,
        )
        m = heading_pat.search(content)
        if not m:
            continue
        # Look in the next 600 chars for the dollar range
        snippet = content[m.start(): m.start() + 600]

        # Match: $2,050 – $2,200 (en-dash, em-dash, or hyphen; may be inside **bold**)
        range_match = re.search(
            r"\\\$([0-9,]+)\s*[–—-]+\s*\\\$([0-9,]+)"
            r"|\$([0-9,]+)\s*[–—-]+\s*\$([0-9,]+)",
            snippet,
        )
        # Match confidence tier
        conf_match = re.search(
            r"Confidence.*?(High|Medium|Low)",
            snippet,
            re.IGNORECASE,
        )

        if range_match:
            # Groups 1,2 = escaped \$ match; groups 3,4 = bare $ match
            low_str = (range_match.group(1) or range_match.group(3)).replace(",", "")
            high_str = (range_match.group(2) or range_match.group(4)).replace(",", "")
            low_disp = range_match.group(1) or range_match.group(3)
            high_disp = range_match.group(2) or range_match.group(4)
            range_str = f"${low_disp} – ${high_disp}"
            confidence = conf_match.group(1).capitalize() if conf_match else "Low"
            results.append({
                "origin": origin,
                "destination": dest,
                "range_low": int(low_str),
                "range_high": int(high_str),
                "range_str": range_str,
                "confidence": confidence,
            })

    return results


def save_run(briefing: dict, signals_summary: dict) -> dict:
    run_id = len(_runs) + 1
    content = briefing.get("content", "")
    record = {
        "id": run_id,
        "generated_at": briefing.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "trade_lane": briefing.get("trade_lane", "TPEB"),
        "content": content,
        "icc_ranges": _parse_icc_ranges(content),
        "used_claude": briefing.get("used_claude", False),
        "error": briefing.get("error"),
        "signal_summary": signals_summary,
        "trigger": briefing.get("trigger", "manual"),
    }
    _runs.insert(0, record)

    # Persist to disk
    filepath = os.path.join(OUTPUT_DIR, f"icc_briefing_{run_id:04d}.json")
    try:
        with open(filepath, "w") as f:
            json.dump(record, f, indent=2)
    except Exception:
        pass

    return record


def get_all_runs() -> List[dict]:
    return list(_runs)


def get_run(run_id: int) -> Optional[dict]:
    for r in _runs:
        if r["id"] == run_id:
            return r
    return None


# Load persisted runs on module import
_load_runs_from_disk()
