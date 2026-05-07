#!/usr/bin/env python3
"""Parse chat-style TradingAgents requests and invoke the OpenClaw adapter.

Examples:
  scripts/openclaw_chat_analyze.py "分析 日月光投控" --dry-run
  scripts/openclaw_chat_analyze.py "用 gpt-5.5 分析 NVDA" --format summary
  scripts/openclaw_chat_analyze.py "分析 台積電 昨天" --format summary
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.openclaw_alias import add_alias, resolve_alias

ADAPTER = REPO_ROOT / "scripts" / "openclaw_analyze.sh"

_TICKER_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")
_ISO_DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
_RELATIVE_DATE_WORDS = {
    "今天": 0,
    "今日": 0,
    "昨天": -1,
    "昨日": -1,
    "前天": -2,
}
_ANALYZE_PATTERNS = (
    re.compile(r"(?:請幫我|幫我|請)?(?:用\s*(?P<model>[A-Za-z0-9._\-/]+)\s*)?(?:分析|研究|看一下)\s*(?P<target>.+?)\s*$", re.I),
    re.compile(r"(?P<target>[A-Za-z0-9._\-\^\u4e00-\u9fff]+)\s*(?:分析|研究|看一下)\s*$", re.I),
)


def extract_date_hint(text: str, today: dt.date | None = None) -> tuple[str, str | None]:
    """Remove chat-style date hints and return an ISO date override.

    ``--date`` still wins when the user passes it explicitly. This helper only
    makes common Telegram messages such as ``分析 台積電 昨天`` behave like a
    human would expect.
    """

    today = today or dt.date.today()

    match = _ISO_DATE_RE.search(text)
    if match:
        date_hint = match.group("date")
        text = _ISO_DATE_RE.sub(" ", text, count=1)
        return " ".join(text.split()), date_hint

    for word, delta_days in _RELATIVE_DATE_WORDS.items():
        if word in text:
            date_hint = (today + dt.timedelta(days=delta_days)).isoformat()
            text = text.replace(word, " ")
            return " ".join(text.split()), date_hint

    return text, None


def parse_chat_request(message: str) -> tuple[str, str | None, str | None]:
    text = message.strip()
    if not text:
        raise SystemExit("message must be non-empty")

    text, date_hint = extract_date_hint(text)

    for pattern in _ANALYZE_PATTERNS:
        match = pattern.search(text)
        if match:
            target = match.group("target").strip(" ，,。！!？?")
            model = match.groupdict().get("model")
            return target, model, date_hint

    # Accept a raw ticker/alias as a convenience.
    if _TICKER_RE.fullmatch(text) or re.search(r"[\u4e00-\u9fff]", text):
        return text, None, date_hint

    raise SystemExit(f"Could not parse analysis target from message: {message!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TradingAgents from a natural-language chat message.")
    parser.add_argument("message", help="Chat message, e.g. '分析 日月光投控'.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD. Defaults to chat date hint or today.")
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
    parser.add_argument(
        "--resolved-ticker",
        default=None,
        help="Ticker resolved externally/LLM for an unknown alias. Persists alias before running.",
    )
    parser.add_argument(
        "--canonical",
        default=None,
        help="Canonical company/security name to store with --resolved-ticker.",
    )
    parser.add_argument(
        "--alias-source",
        default="llm",
        help="Source label stored when --resolved-ticker persists an alias. Default: llm.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target, model_hint, date_hint = parse_chat_request(args.message)
    deep_model = model_hint or args.deep_model or "gpt-5.5"
    trade_date = args.date or date_hint or dt.date.today().isoformat()

    run_target = target
    if args.resolved_ticker:
        add_alias(
            alias=target,
            ticker=args.resolved_ticker,
            canonical=args.canonical or target,
            source=args.alias_source,
        )
        # Use the freshly resolved ticker for this subprocess too. The alias is
        # persisted for future runs, but tests and alternate alias paths should
        # not require the child process to re-read the same store.
        run_target = args.resolved_ticker
    elif resolve_alias(target) is None and re.search(r"[\u4e00-\u9fff]", target):
        raise SystemExit(
            f"Unknown alias: {target!r}. Resolve the ticker first, then rerun with "
            f"--resolved-ticker <TICKER> --canonical <NAME> to persist it."
        )

    cmd = [
        str(ADAPTER),
        "--ticker", run_target,
        "--date", trade_date,
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
