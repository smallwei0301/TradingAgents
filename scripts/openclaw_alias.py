#!/usr/bin/env python3
"""Manage OpenClaw natural-language ticker aliases for TradingAgents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = REPO_ROOT / "OPENCLAW_ALIASES.json"
_TICKER_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")


def load_aliases(path: Path | None = None) -> dict[str, Any]:
    path = path or ALIASES_PATH
    if not path.exists():
        return {"aliases": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_aliases(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or ALIASES_PATH
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def normalize_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise SystemExit("alias must be non-empty")
    return key.upper() if _TICKER_RE.fullmatch(key) else key


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not ticker:
        raise SystemExit("ticker must be non-empty")
    if not _TICKER_RE.fullmatch(ticker):
        raise SystemExit(f"ticker contains invalid characters: {value!r}")
    return ticker


def resolve_alias(value: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    data = data or load_aliases()
    aliases = data.get("aliases", {})
    candidates = [value.strip(), value.strip().upper()]
    for key in candidates:
        if key in aliases:
            return aliases[key]
    return None


def add_alias(alias: str, ticker: str, canonical: str | None, source: str) -> dict[str, Any]:
    data = load_aliases()
    aliases = data.setdefault("aliases", {})
    key = normalize_key(alias)
    ticker = normalize_ticker(ticker)
    entry = {
        "ticker": ticker,
        "canonical": canonical or alias.strip(),
        "source": source,
        "updated_at": dt.date.today().isoformat(),
    }
    aliases[key] = entry
    # Also store the ticker itself so direct ticker lookup is stable.
    aliases.setdefault(ticker, {**entry, "source": "ticker" if source == "llm" else source})
    save_aliases(data)
    return entry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage OpenClaw ticker aliases.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="Add or update an alias mapping.")
    add.add_argument("--alias", required=True, help="Alias text, e.g. 日月光投控")
    add.add_argument("--ticker", required=True, help="Resolved ticker, e.g. 3711.TW")
    add.add_argument("--canonical", default=None, help="Canonical company/security name.")
    add.add_argument("--source", default="llm", help="Resolution source: llm, user, seed, search, etc.")

    res = sub.add_parser("resolve", help="Resolve an alias to a ticker.")
    res.add_argument("alias", help="Alias or ticker to resolve.")
    res.add_argument("--json", action="store_true", help="Print full JSON entry.")

    sub.add_parser("list", help="List aliases as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd == "add":
        entry = add_alias(args.alias, args.ticker, args.canonical, args.source)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "resolve":
        entry = resolve_alias(args.alias)
        if not entry:
            return 1
        print(json.dumps(entry, ensure_ascii=False, indent=2) if args.json else entry["ticker"])
        return 0
    if args.cmd == "list":
        print(json.dumps(load_aliases(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
