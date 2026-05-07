#!/usr/bin/env python3
"""Parse chat-style TradingAgents requests and invoke the OpenClaw adapter.

Examples:
  scripts/openclaw_chat_analyze.py "分析 日月光投控" --dry-run
  scripts/openclaw_chat_analyze.py "用 gpt-5.5 分析 NVDA" --format summary
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = REPO_ROOT / "scripts" / "openclaw_analyze.sh"

_TICKER_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")
_ANALYZE_PATTERNS = (
    re.compile(r"(?:請幫我|幫我|請)?(?:用\s*(?P<model>[A-Za-z0-9._\-/]+)\s*)?(?:分析|研究|看一下)\s*(?P<target>.+?)\s*$", re.I),
    re.compile(r"(?P<target>[A-Za-z0-9._\-\^\u4e00-\u9fff]+)\s*(?:分析|研究|看一下)\s*$", re.I),
)


def parse_chat_request(message: str) -> tuple[str, str | None]:
    text = message.strip()
    if not text:
        raise SystemExit("message must be non-empty")

    for pattern in _ANALYZE_PATTERNS:
        match = pattern.search(text)
        if match:
            target = match.group("target").strip(" ，,。！!？?")
            model = match.groupdict().get("model")
            return target, model

    # Accept a raw ticker/alias as a convenience.
    if _TICKER_RE.fullmatch(text) or re.search(r"[\u4e00-\u9fff]", text):
        return text, None

    raise SystemExit(f"Could not parse analysis target from message: {message!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TradingAgents from a natural-language chat message.")
    parser.add_argument("message", help="Chat message, e.g. '分析 日月光投控'.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--provider", default="openai", help="LLM provider. Default: openai.")
    parser.add_argument("--quick-model", default="gpt-5.4-mini", help="Quick model.")
    parser.add_argument("--deep-model", default=None, help="Deep model. Message model hint wins when present.")
    parser.add_argument("--format", choices=("markdown", "json", "summary"), default="summary")
    parser.add_argument("--output-language", default="繁體中文")
    parser.add_argument("--research-depth", type=int, default=1)
    parser.add_argument("--analysts", default="market,social,news,fundamentals")
    parser.add_argument("--checkpoint", action="store_true")
    parser.add_argument("--clear-checkpoints", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target, model_hint = parse_chat_request(args.message)
    deep_model = model_hint or args.deep_model or "gpt-5.5"

    cmd = [
        str(ADAPTER),
        "--ticker", target,
        "--date", args.date,
        "--provider", args.provider,
        "--quick-model", args.quick_model,
        "--deep-model", deep_model,
        "--output-language", args.output_language,
        "--research-depth", str(args.research_depth),
        "--analysts", args.analysts,
        "--format", args.format,
    ]
    if args.checkpoint:
        cmd.append("--checkpoint")
    if args.clear_checkpoints:
        cmd.append("--clear-checkpoints")
    if args.dry_run:
        cmd.append("--dry-run")

    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
