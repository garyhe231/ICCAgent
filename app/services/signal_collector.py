"""
Signal Collector — Phase 0

Aggregates all signal layers:
  Layer 1: Internal (local seed data — Phase 0; Snowflake in Phase 1)
  Layer 2: Market Benchmarks (web search for SCFI, Xeneta, competitor news)
  Layer 3: Carrier Pricing (web search for GRI announcements, blank sailings)
  Qualitative: Analyst-submitted signals (in-memory store + local seed)

Each signal is tagged with its source and whether it is real data or web-search fallback,
so the AI can accurately label data gaps in the output.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from app.config import DATA_DIR

# ---------------------------------------------------------------------------
# In-memory qualitative signal store (survives a single server session)
# In Phase 1 this would persist to Snowflake / Postgres
# ---------------------------------------------------------------------------
_qualitative_signals: List[dict] = []
_qualitative_signals_loaded = False


def _load_seed_qualitative() -> None:
    global _qualitative_signals_loaded
    if _qualitative_signals_loaded:
        return
    for seed_file in ("local_signals.json", "fewb_signals.json"):
        seed_path = os.path.join(DATA_DIR, seed_file)
        try:
            with open(seed_path) as f:
                seed = json.load(f)
            for entry in seed.get("qualitative_signals", {}).get("entries", []):
                _qualitative_signals.append(entry)
        except Exception:
            pass
    _qualitative_signals_loaded = True


def add_qualitative_signal(author: str, text: str, tags: Optional[List[str]] = None) -> dict:
    """Add a new analyst-submitted qualitative signal."""
    _load_seed_qualitative()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "author": author,
        "text": text,
        "tags": tags or [],
    }
    _qualitative_signals.insert(0, entry)
    return entry


def get_qualitative_signals() -> List[dict]:
    _load_seed_qualitative()
    return list(_qualitative_signals)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_html(url: str, timeout: int = 10) -> Optional[str]:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ICCAgent/1.0)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _text_from_html(html: str, max_chars: int = 3000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:max_chars]


def _web_signal(label: str, url: str, max_chars: int = 2000) -> dict:
    html = _fetch_html(url)
    if html:
        return {
            "source": label,
            "url": url,
            "status": "ok",
            "data_type": "web_search_fallback",
            "data": _text_from_html(html, max_chars),
        }
    return {
        "source": label,
        "url": url,
        "status": "failed",
        "data_type": "web_search_fallback",
        "data": "",
    }


# Seed file per trade lane
_SEED_FILES = {
    "TPEB": "local_signals.json",
    "FEWB": "fewb_signals.json",
}


# ---------------------------------------------------------------------------
# Layer 1: Internal signals (local seed in Phase 0)
# ---------------------------------------------------------------------------

def collect_internal_signals(trade_lanes: Optional[List[str]] = None) -> dict:
    """Load internal seed data for one or more trade lanes, merging rows."""
    lanes = trade_lanes or ["TPEB"]
    all_wb: List[dict] = []
    all_va: List[dict] = []
    errors = []

    for lane in lanes:
        seed_file = _SEED_FILES.get(lane)
        if not seed_file:
            continue
        seed_path = os.path.join(DATA_DIR, seed_file)
        try:
            with open(seed_path) as f:
                seed = json.load(f)
            for row in seed.get("weighted_buy", {}).get("data", []):
                row["trade_lane"] = lane
                all_wb.append(row)
            for row in seed.get("volume_allocation", {}).get("data", []):
                row["trade_lane"] = lane
                all_va.append(row)
        except Exception as e:
            errors.append(str(e))

    status = "failed" if errors and not all_wb else "ok"
    return {
        "weighted_buy": {
            "source": "Snowflake / Cost Library (Phase 0: local seed)",
            "status": status,
            "data_type": "local_seed",
            "data": all_wb,
        },
        "volume_allocation": {
            "source": "Looker / Snowflake (Phase 0: local seed)",
            "status": status,
            "data_type": "local_seed",
            "data": all_va,
        },
    }


# ---------------------------------------------------------------------------
# Layer 2: Market benchmark signals (web search fallback)
# ---------------------------------------------------------------------------

MARKET_SOURCES = {
    "scfi_freightos": {
        "label": "SCFI / Freightos Baltic Index",
        "url": "https://fbx.freightos.com/",
        "lanes": ["TPEB", "FEWB"],
    },
    "freightwaves_rates": {
        "label": "FreightWaves — Ocean Rate Trends",
        "url": "https://www.freightwaves.com/news/category/ocean",
        "lanes": ["TPEB", "FEWB"],
    },
    "xeneta_news": {
        "label": "Xeneta Market Intelligence",
        "url": "https://www.xeneta.com/blog",
        "lanes": ["TPEB", "FEWB"],
    },
    "drewry_wci": {
        "label": "Drewry World Container Index",
        "url": "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry",
        "lanes": ["TPEB", "FEWB"],
    },
    "container_news_europe": {
        "label": "Container News — Europe Market",
        "url": "https://container-news.com/category/european-shipping/",
        "lanes": ["FEWB"],
    },
}


def _collect_sources_parallel(sources: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch all sources concurrently, 5 second timeout per request."""
    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_web_signal, meta["label"], meta["url"]): key
            for key, meta in sources.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {
                    "source": sources[key]["label"],
                    "status": "failed",
                    "data_type": "web_search_fallback",
                    "data": "",
                }
    return results


def collect_market_signals(trade_lanes: Optional[List[str]] = None) -> Dict[str, Any]:
    lanes = set(trade_lanes or ["TPEB"])
    filtered = {k: v for k, v in MARKET_SOURCES.items() if set(v.get("lanes", [])) & lanes}
    return _collect_sources_parallel(filtered)


# ---------------------------------------------------------------------------
# Layer 3: Carrier pricing signals (web search fallback)
# ---------------------------------------------------------------------------

CARRIER_SOURCES = {
    "maersk_news": {
        "label": "Maersk Rate & GRI Announcements",
        "url": "https://www.maersk.com/news",
        "lanes": ["TPEB", "FEWB"],
    },
    "msc_news": {
        "label": "MSC Rate Announcements",
        "url": "https://www.msc.com/en/press-room",
        "lanes": ["TPEB", "FEWB"],
    },
    "one_news": {
        "label": "ONE Rate Announcements",
        "url": "https://www.one-line.com/en/news-media",
        "lanes": ["TPEB"],
    },
    "alphaliner_blank": {
        "label": "Alphaliner — Blank Sailings & Capacity",
        "url": "https://alphaliner.axsmarine.com/PublicTop100/",
        "lanes": ["TPEB", "FEWB"],
    },
    "container_news_gri": {
        "label": "Container News — GRI & Market Updates",
        "url": "https://container-news.com/category/ocean-freight/",
        "lanes": ["TPEB", "FEWB"],
    },
    "cma_cgm_news": {
        "label": "CMA CGM Rate Announcements",
        "url": "https://www.cma-cgm.com/news",
        "lanes": ["FEWB"],
    },
    "hapag_news": {
        "label": "Hapag-Lloyd Rate Announcements",
        "url": "https://www.hapag-lloyd.com/en/online-business/news.html",
        "lanes": ["FEWB"],
    },
}


def collect_carrier_signals(trade_lanes: Optional[List[str]] = None) -> Dict[str, Any]:
    lanes = set(trade_lanes or ["TPEB"])
    filtered = {k: v for k, v in CARRIER_SOURCES.items() if set(v.get("lanes", [])) & lanes}
    return _collect_sources_parallel(filtered)


# ---------------------------------------------------------------------------
# Master collector
# ---------------------------------------------------------------------------

def collect_all_signals(extra_context: str = "", trade_lanes: Optional[List[str]] = None) -> dict:
    """Run all three signal layers for the given trade lanes and return a unified payload."""
    lanes = trade_lanes or ["TPEB"]
    started_at = datetime.now(timezone.utc).isoformat()

    internal = collect_internal_signals(trade_lanes=lanes)
    market = collect_market_signals(trade_lanes=lanes)
    carrier = collect_carrier_signals(trade_lanes=lanes)
    qualitative = get_qualitative_signals()

    all_sources = {**market, **carrier}
    ok = sum(1 for v in all_sources.values() if v.get("status") == "ok")
    failed = sum(1 for v in all_sources.values() if v.get("status") != "ok")
    internal_ok = sum(1 for v in internal.values() if v.get("status") == "ok")

    return {
        "collected_at": started_at,
        "extra_context": extra_context,
        "trade_lanes": lanes,
        "signals": {
            "internal": internal,
            "market": market,
            "carrier": carrier,
            "qualitative": qualitative,
        },
        "summary": {
            "internal_ok": internal_ok,
            "web_ok": ok,
            "web_failed": failed,
            "qualitative_count": len(qualitative),
            "trade_lanes": lanes,
        },
    }
