"""
AI Synthesizer — uses Claude to produce the ICC briefing document.

Output structure (5 sections per PRD):
  1. Recommended ICC Range  — range per port-group pair, confidence, rationale
  2. Signal Dashboard       — summary of signals by category
  3. Watch Items            — uncertain/contradictory signals
  4. Market Context         — SCFI/Xeneta/competitor spread vs recommendation
  5. Data Gaps              — explicitly flagged missing signals
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional

import boto3
from botocore.config import Config

from app.config import TRADE_LANES

# Resolve model ID — use Sonnet (Opus ARN times out on this Bedrock setup)
_MODEL = (
    os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL")
    or os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL")
    or "anthropic.claude-sonnet-4-5"
)
_AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=_AWS_REGION,
            config=Config(read_timeout=60, connect_timeout=10),
        )
    return _bedrock_client


def _invoke(prompt: str, max_tokens: int = 4096) -> str:
    """Call Claude via boto3 bedrock-runtime."""
    client = _get_bedrock_client()
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = client.invoke_model(
        modelId=_MODEL,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(signals: dict, run_date: str, extra_context: str, trade_lanes: Optional[List[str]] = None) -> str:
    # Serialize internal signals compactly
    internal = signals.get("internal", {})
    weighted_buy_rows = internal.get("weighted_buy", {}).get("data", [])
    volume_alloc_rows = internal.get("volume_allocation", {}).get("data", [])

    # Summarize web signals (600 chars each to keep prompt lean and fast)
    market_summaries = []
    for key, sig in signals.get("market", {}).items():
        status = sig.get("status", "failed")
        snippet = (sig.get("data", "") or "")[:600]
        market_summaries.append(f"[{sig['source']} | {status}]\n{snippet}")

    carrier_summaries = []
    for key, sig in signals.get("carrier", {}).items():
        status = sig.get("status", "failed")
        snippet = (sig.get("data", "") or "")[:600]
        carrier_summaries.append(f"[{sig['source']} | {status}]\n{snippet}")

    # Qualitative signals
    qual_entries = signals.get("qualitative", [])
    qual_text = "\n".join(
        f"- [{e['timestamp'][:10]} | {e['author']}] {e['text']}"
        for e in qual_entries[:10]
    )

    wb_text = json.dumps(weighted_buy_rows, indent=2) if weighted_buy_rows else "(not available)"
    va_text = json.dumps(volume_alloc_rows, indent=2) if volume_alloc_rows else "(not available)"
    market_text = "\n\n".join(market_summaries) if market_summaries else "(none)"
    carrier_text = "\n\n".join(carrier_summaries) if carrier_summaries else "(none)"
    qual_text = qual_text if qual_text.strip() else "(none submitted)"

    lanes = trade_lanes or ["TPEB"]
    extra = f"\n\nADDITIONAL CONTEXT FROM ANALYST:\n{extra_context}" if extra_context.strip() else ""

    # Build lane scope description
    lane_scope_lines = []
    all_port_pairs = []
    for lane in lanes:
        cfg = TRADE_LANES.get(lane, {})
        pairs = cfg.get("port_pairs", [])
        all_port_pairs.extend(pairs)
        pairs_str = " | ".join(f"{o} → {d}" for o, d in pairs)
        lane_scope_lines.append(f"  {lane} ({cfg.get('label', lane)}): {pairs_str}")
    lane_scope = "\n".join(lane_scope_lines)
    port_pairs_str = " | ".join(f"{o} → {d}" for o, d in all_port_pairs)

    return f"""You are the ICC AI Agent for Flexport's Procurement team.

Your job is to synthesize structured and unstructured market signals into a ready-to-use ICC (Internal Carrier Cost) briefing document — replicating the judgment of a senior Procurement/ROM analyst.

Run date: {run_date}
Trade lanes in scope:
{lane_scope}
Equipment: 40ft FAK (Open Carrier Standard, V1 scope){extra}

---
LAYER 1 — INTERNAL SIGNALS (Flexport data)

Weighted Buy (FAK/contracted rates by port pair):
{wb_text}

Volume Allocation by Carrier:
{va_text}

Note: Internal data is Phase-0 local seed. Label these as "local seed data" in your output, not live Snowflake data.

---
LAYER 2 — MARKET BENCHMARK SIGNALS (web search)

{market_text}

---
LAYER 3 — CARRIER PRICING SIGNALS (web search)

{carrier_text}

---
QUALITATIVE SIGNALS (analyst-submitted intel)

{qual_text}

---
INSTRUCTIONS

Produce the ICC briefing document with exactly these five sections. Be specific and actionable. Do not be generic or formulaic. Where signals are contradictory, say so clearly. Where data is missing, name the gap explicitly.

## 1. RECOMMENDED ICC RANGE

For each port-group pair in scope, provide:
- Recommended FAK ICC range ($/40ft)
- Confidence tier: High / Medium / Low
- 2-3 sentence rationale grounded in the signals above

Port pairs in scope: {port_pairs_str}

Group port pairs by trade lane (TPEB section, then FEWB section) if multiple lanes are in scope.

Important: The recommended range should reflect the TRUE FREIGHT-FORWARDER MARKET RATE, not just Flexport's weighted buy. Adjust away from weighted buy where market signals indicate a different level. Flag cost-plus bias if you see it.

## 2. SIGNAL DASHBOARD

A concise table or structured summary of the key signals that drove the recommendation, organized by:
- Carrier Pricing Signals
- Market Benchmark Signals
- Qualitative Intel

For each signal, note: source, what it says, and its directional impact on ICC (upward / downward / neutral / unclear).

## 3. WATCH ITEMS

List 2-5 signals that are uncertain, contradictory, or require human judgment before the ICC Setting Meeting. For each, explain why it's a watch item and what information would resolve it.

## 4. MARKET CONTEXT

Summarize:
- Current freight index levels (SCFI / Drewry WCI / Freightos) and trend direction
- Competitor forwarder rate spread vs. recommended ICC
- How the recommended ICC range sits relative to market benchmarks (at market / above / below — and by how much)

## 5. DATA GAPS

List every signal category from the PRD that was NOT available in this run. For each gap:
- Signal name
- Expected source (Snowflake / Xeneta API / etc.)
- Phase when it will be available (Phase 1 / Phase 2)
- Impact on confidence: does this gap raise or lower your confidence tier?

End with a one-paragraph CONFIDENCE SUMMARY explaining overall confidence for this run and the primary factors limiting it.

---
FORMAT: Use markdown with clear headers. Be direct and specific. This document is the pre-read for the Monday ICC Prep Meeting — it must be ready to use without further editing.
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def synthesize_icc_briefing(signals: dict, extra_context: str = "", trade_lanes: Optional[List[str]] = None) -> dict:
    """Call Claude to produce the ICC briefing. Returns structured result."""
    lanes = trade_lanes or ["TPEB"]
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = _build_prompt(signals, run_date, extra_context, trade_lanes=lanes)

    try:
        content = _invoke(prompt, max_tokens=2000)
        used_claude = True
        error = None
    except Exception as e:
        content = _fallback_briefing(signals, run_date)
        used_claude = False
        error = str(e)

    return {
        "generated_at": run_date,
        "trade_lane": " + ".join(lanes),
        "trade_lanes": lanes,
        "content": content,
        "used_claude": used_claude,
        "error": error,
        "signal_summary": signals.get("summary", {}),
    }


def _fallback_briefing(signals: dict, run_date: str) -> str:
    """Minimal fallback when Claude is unavailable."""
    summary = signals.get("summary", {})
    return f"""# ICC Briefing — {run_date}
## Status: Claude API Unavailable

This is a fallback response. The Claude API was not reachable.

**Signal collection summary:**
- Internal signals available: {summary.get('internal_ok', 0)}/2
- Web signals OK: {summary.get('web_ok', 0)}
- Web signals failed: {summary.get('web_failed', 0)}
- Qualitative signals: {summary.get('qualitative_count', 0)}

Please check your ANTHROPIC_API_KEY and retry.
"""
