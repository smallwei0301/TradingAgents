#!/usr/bin/env python3
"""OpenClaw adapter for running TradingAgents non-interactively.

This script is intentionally thin: it keeps the TradingAgents core untouched and
provides a stable CLI surface that OpenClaw can call from skills, cron jobs, or
chat commands.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

from tradingagents.default_config import DEFAULT_CONFIG

ANALYST_ORDER = ("market", "social", "news", "fundamentals")
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")
DEFAULT_PROVIDER_MODELS = {
    "openai": ("gpt-5.4-mini", "gpt-5.4"),
    "google": ("gemini-3.1-flash", "gemini-3.1-pro"),
    "anthropic": ("claude-4.6-sonnet", "claude-4.6-sonnet"),
    "deepseek": ("deepseek-chat", "deepseek-reasoner"),
    "qwen": ("qwen-plus", "qwen-max"),
    "glm": ("glm-4.6", "glm-4.6"),
    "openrouter": ("openai/gpt-5.4-mini", "openai/gpt-5.4"),
    "ollama": ("llama3.1", "llama3.1"),
    "xai": ("grok-4-fast", "grok-4"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TradingAgents from OpenClaw without the interactive CLI."
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. NVDA, TSLA, 7203.T")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Analysis date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("TRADINGAGENTS_LLM_PROVIDER", DEFAULT_CONFIG.get("llm_provider", "openai")),
        help="LLM provider: openai, google, anthropic, xai, deepseek, qwen, glm, openrouter, azure, ollama.",
    )
    parser.add_argument("--quick-model", default=None, help="Model for quick/shallow tasks.")
    parser.add_argument("--deep-model", default=None, help="Model for deep/reasoning tasks.")
    parser.add_argument("--backend-url", default=None, help="Optional provider base URL/proxy endpoint.")
    parser.add_argument("--research-depth", type=int, default=1, help="Debate/risk rounds. Default: 1.")
    parser.add_argument(
        "--analysts",
        default=",".join(ANALYST_ORDER),
        help="Comma-separated analysts: market,social,news,fundamentals.",
    )
    parser.add_argument("--output-language", default="繁體中文", help="Report language. Default: 繁體中文.")
    parser.add_argument("--results-dir", default=None, help="Override TradingAgents results directory.")
    parser.add_argument("--cache-dir", default=None, help="Override TradingAgents cache directory.")
    parser.add_argument("--memory-log-path", default=None, help="Override persistent decision log path.")
    parser.add_argument("--checkpoint", action="store_true", help="Enable checkpoint/resume.")
    parser.add_argument("--debug", action="store_true", help="Pretty-print LangChain messages while running.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json", "summary"),
        default="markdown",
        help="Stdout format. Use summary for chat surfaces. Default: markdown.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and print the effective config without calling LLMs.",
    )
    return parser.parse_args()


def validate_date(value: str) -> str:
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid --date '{value}'. Use YYYY-MM-DD.") from exc
    if parsed > dt.date.today():
        raise SystemExit("--date cannot be in the future.")
    return parsed.isoformat()


def parse_analysts(value: str) -> list[str]:
    requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = sorted(set(requested) - set(ANALYST_ORDER))
    if invalid:
        raise SystemExit(f"Invalid analysts: {', '.join(invalid)}. Allowed: {', '.join(ANALYST_ORDER)}")
    # Preserve canonical graph order, regardless of user input order.
    return [name for name in ANALYST_ORDER if name in requested]


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Local copy to keep --dry-run dependency-free before package install."""
    if not isinstance(value, str) or not value:
        raise SystemExit(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        raise SystemExit(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise SystemExit(f"ticker contains characters not allowed in a filesystem path: {value!r}")
    if set(value) == {"."}:
        raise SystemExit(f"ticker cannot consist solely of dots: {value!r}")
    return value


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    provider = args.provider.lower()
    default_quick, default_deep = DEFAULT_PROVIDER_MODELS.get(
        provider,
        (DEFAULT_CONFIG["quick_think_llm"], DEFAULT_CONFIG["deep_think_llm"]),
    )

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = provider
    config["quick_think_llm"] = args.quick_model or os.getenv("TRADINGAGENTS_QUICK_MODEL") or default_quick
    config["deep_think_llm"] = args.deep_model or os.getenv("TRADINGAGENTS_DEEP_MODEL") or default_deep
    config["backend_url"] = args.backend_url or os.getenv("TRADINGAGENTS_BACKEND_URL") or DEFAULT_CONFIG.get("backend_url")
    config["max_debate_rounds"] = args.research_depth
    config["max_risk_discuss_rounds"] = args.research_depth
    config["checkpoint_enabled"] = args.checkpoint
    config["output_language"] = args.output_language

    if args.results_dir:
        config["results_dir"] = args.results_dir
    if args.cache_dir:
        config["data_cache_dir"] = args.cache_dir
    if args.memory_log_path:
        config["memory_log_path"] = args.memory_log_path

    return config


def compact_state(final_state: dict[str, Any]) -> dict[str, Any]:
    risk = final_state.get("risk_debate_state") or {}
    debate = final_state.get("investment_debate_state") or {}
    return {
        "company_of_interest": final_state.get("company_of_interest"),
        "trade_date": final_state.get("trade_date"),
        "market_report": final_state.get("market_report"),
        "sentiment_report": final_state.get("sentiment_report"),
        "news_report": final_state.get("news_report"),
        "fundamentals_report": final_state.get("fundamentals_report"),
        "bull_research": debate.get("bull_history"),
        "bear_research": debate.get("bear_history"),
        "research_manager_decision": debate.get("judge_decision"),
        "trader_investment_plan": final_state.get("trader_investment_plan"),
        "aggressive_risk_analysis": risk.get("aggressive_history"),
        "conservative_risk_analysis": risk.get("conservative_history"),
        "neutral_risk_analysis": risk.get("neutral_history"),
        "portfolio_manager_decision": final_state.get("final_trade_decision") or risk.get("judge_decision"),
    }


def extract_executive_summary(text: str) -> str:
    """Extract the Portfolio Manager executive summary when present."""
    if not text:
        return ""
    marker = "**Executive Summary**:"
    start = text.find(marker)
    if start == -1:
        return text.strip().split("\n\n", 1)[0].strip()
    start += len(marker)
    next_marker = text.find("\n\n**", start)
    if next_marker == -1:
        return text[start:].strip()
    return text[start:next_marker].strip()


def render_summary(payload: dict[str, Any]) -> str:
    pm_decision = payload["state"].get("portfolio_manager_decision") or ""
    executive_summary = extract_executive_summary(pm_decision)
    lines = [
        f"TradingAgents：{payload['ticker']} / {payload['date']}",
        f"Decision：{payload['decision']}",
    ]
    if executive_summary:
        lines.extend(["", executive_summary])
    lines.extend(["", f"完整報告：{payload['report_path']}"])
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(payload: dict[str, Any]) -> str:
    sections = [
        f"# TradingAgents Analysis: {payload['ticker']}",
        "",
        f"- Date: {payload['date']}",
        f"- Decision: {payload['decision']}",
        f"- Provider: {payload['provider']}",
        f"- Quick model: {payload['quick_model']}",
        f"- Deep model: {payload['deep_model']}",
        f"- Full report: `{payload['report_path']}`",
        "",
        "## Portfolio Manager Decision",
        payload["state"].get("portfolio_manager_decision") or "",
        "",
    ]

    optional_sections = (
        ("Trader Plan", "trader_investment_plan"),
        ("Research Manager Decision", "research_manager_decision"),
        ("Market Report", "market_report"),
        ("Sentiment Report", "sentiment_report"),
        ("News Report", "news_report"),
        ("Fundamentals Report", "fundamentals_report"),
    )
    for title, key in optional_sections:
        content = payload["state"].get(key)
        if content:
            sections.extend([f"## {title}", content, ""])

    return "\n".join(sections).rstrip() + "\n"


def save_outputs(payload: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "complete_report.md").write_text(render_markdown(payload), encoding="utf-8")
    (report_dir / "chat_summary.md").write_text(render_summary(payload), encoding="utf-8")


def main() -> int:
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    ticker = args.ticker.strip().upper()
    trade_date = validate_date(args.date)
    analysts = parse_analysts(args.analysts)
    config = build_config(args)

    safe_ticker = safe_ticker_component(ticker)
    report_dir = Path(config["results_dir"]) / safe_ticker / trade_date / "openclaw_report"

    if args.dry_run:
        dry_payload = {
            "ticker": ticker,
            "date": trade_date,
            "analysts": analysts,
            "provider": config["llm_provider"],
            "quick_model": config["quick_think_llm"],
            "deep_model": config["deep_think_llm"],
            "research_depth": args.research_depth,
            "output_language": config["output_language"],
            "results_dir": config["results_dir"],
            "cache_dir": config["data_cache_dir"],
            "memory_log_path": config["memory_log_path"],
            "checkpoint": config["checkpoint_enabled"],
            "report_path": str(report_dir / "complete_report.md"),
        }
        print(json.dumps(dry_payload, ensure_ascii=False, indent=2))
        return 0

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(
        selected_analysts=analysts,
        debug=args.debug,
        config=config,
    )
    final_state, decision = graph.propagate(ticker, trade_date)

    payload = {
        "ticker": ticker,
        "date": trade_date,
        "decision": decision,
        "provider": config["llm_provider"],
        "quick_model": config["quick_think_llm"],
        "deep_model": config["deep_think_llm"],
        "research_depth": args.research_depth,
        "output_language": config["output_language"],
        "report_path": str(report_dir / "complete_report.md"),
        "state": compact_state(final_state),
    }
    save_outputs(payload, report_dir)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "summary":
        print(render_summary(payload))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
