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
from functools import wraps
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.openclaw_alias import resolve_alias

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

from tradingagents.default_config import DEFAULT_CONFIG

ANALYST_ORDER = ("market", "social", "news", "fundamentals")
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")
DEFAULT_PROVIDER_MODELS = {
    "openai": ("gpt-5.4-mini", "gpt-5.5"),
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
    parser.add_argument("--clear-checkpoints", action="store_true", help="Delete all saved checkpoints before running.")
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


def run_cli_equivalent_analysis(
    *,
    ticker: str,
    trade_date: str,
    analysts: list[str],
    config: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], Path, Path]:
    """Run the same non-interactive graph path used by ``tradingagents analyze``.

    The repository CLI does not call ``TradingAgentsGraph.propagate()``. It
    builds an initial state, calls ``graph.graph.stream(...)`` directly, writes
    ``message_tool.log`` via ``MessageBuffer`` decorators, persists incremental
    report sections under ``reports/``, then saves the final report through
    ``save_report_to_disk()``. This function mirrors that path so OpenClaw's
    adapter is operationally aligned with the repo CLI rather than merely using
    the same graph core.
    """

    from cli.main import (
        ANALYST_AGENT_NAMES,
        classify_message_type,
        message_buffer,
        save_report_to_disk,
        update_analyst_statuses,
        update_research_team_status,
    )
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    stats_handler = StatsCallbackHandler()
    graph = TradingAgentsGraph(
        selected_analysts=analysts,
        debug=True,
        config=config,
        callbacks=[stats_handler],
    )

    message_buffer.init_for_analysis(analysts)

    safe_ticker = safe_ticker_component(ticker)
    results_dir = Path(config["results_dir"]) / safe_ticker / trade_date
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")

        return wrapper

    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, tool_args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")

        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)

        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                section_content = obj.report_sections[section_name]
                if section_content:
                    file_name = f"{section_name}.md"
                    text = (
                        "\n".join(str(item) for item in section_content)
                        if isinstance(section_content, list)
                        else section_content
                    )
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)

        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(
        message_buffer, "update_report_section"
    )

    message_buffer.add_message("System", f"Selected ticker: {ticker}")
    message_buffer.add_message("System", f"Analysis date: {trade_date}")
    message_buffer.add_message("System", f"Selected analysts: {', '.join(analysts)}")

    if analysts:
        message_buffer.update_agent_status(ANALYST_AGENT_NAMES[analysts[0]], "in_progress")

    init_agent_state = graph.propagator.create_initial_state(ticker, trade_date)
    graph_args = graph.propagator.get_graph_args(callbacks=[stats_handler])

    trace = []
    for chunk in graph.graph.stream(init_agent_state, **graph_args):
        for message in chunk.get("messages", []):
            msg_id = getattr(message, "id", None)
            if msg_id is not None:
                if msg_id in message_buffer._processed_message_ids:
                    continue
                message_buffer._processed_message_ids.add(msg_id)

            msg_type, content = classify_message_type(message)
            if content and content.strip():
                message_buffer.add_message(msg_type, content)

            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    if isinstance(tool_call, dict):
                        message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                    else:
                        message_buffer.add_tool_call(tool_call.name, tool_call.args)

        update_analyst_statuses(message_buffer, chunk)

        if chunk.get("investment_debate_state"):
            debate_state = chunk["investment_debate_state"]
            bull_hist = debate_state.get("bull_history", "").strip()
            bear_hist = debate_state.get("bear_history", "").strip()
            judge = debate_state.get("judge_decision", "").strip()

            if bull_hist or bear_hist:
                update_research_team_status("in_progress")
            if bull_hist:
                message_buffer.update_report_section(
                    "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                )
            if bear_hist:
                message_buffer.update_report_section(
                    "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                )
            if judge:
                message_buffer.update_report_section(
                    "investment_plan", f"### Research Manager Decision\n{judge}"
                )
                update_research_team_status("completed")
                message_buffer.update_agent_status("Trader", "in_progress")

        if chunk.get("trader_investment_plan"):
            message_buffer.update_report_section("trader_investment_plan", chunk["trader_investment_plan"])
            if message_buffer.agent_status.get("Trader") != "completed":
                message_buffer.update_agent_status("Trader", "completed")
                message_buffer.update_agent_status("Aggressive Analyst", "in_progress")

        if chunk.get("risk_debate_state"):
            risk_state = chunk["risk_debate_state"]
            agg_hist = risk_state.get("aggressive_history", "").strip()
            con_hist = risk_state.get("conservative_history", "").strip()
            neu_hist = risk_state.get("neutral_history", "").strip()
            judge = risk_state.get("judge_decision", "").strip()

            if agg_hist:
                if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                    message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                message_buffer.update_report_section(
                    "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                )
            if con_hist:
                if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                    message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                message_buffer.update_report_section(
                    "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                )
            if neu_hist:
                if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                    message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                message_buffer.update_report_section(
                    "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                )
            if judge:
                if message_buffer.agent_status.get("Portfolio Manager") != "completed":
                    message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Portfolio Manager Decision\n{judge}"
                    )
                    message_buffer.update_agent_status("Aggressive Analyst", "completed")
                    message_buffer.update_agent_status("Conservative Analyst", "completed")
                    message_buffer.update_agent_status("Neutral Analyst", "completed")
                    message_buffer.update_agent_status("Portfolio Manager", "completed")

        trace.append(chunk)

    if not trace:
        raise RuntimeError("TradingAgents graph produced no chunks.")

    final_state = trace[-1]
    decision = graph.process_signal(final_state["final_trade_decision"])

    for agent in message_buffer.agent_status:
        message_buffer.update_agent_status(agent, "completed")

    message_buffer.add_message("System", f"Completed analysis for {trade_date}")

    for section in message_buffer.report_sections.keys():
        if section in final_state:
            message_buffer.update_report_section(section, final_state[section])

    report_file = save_report_to_disk(final_state, ticker, report_dir)

    return final_state, decision, stats_handler.get_stats(), report_file, log_file


def save_outputs(payload: dict[str, Any], report_dir: Path, final_state: dict[str, Any] | None = None) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if final_state is None:
        (report_dir / "complete_report.md").write_text(render_markdown(payload), encoding="utf-8")

    (report_dir / "chat_summary.md").write_text(render_summary(payload), encoding="utf-8")


def main() -> int:
    if load_dotenv:
        load_dotenv()

    args = parse_args()
    requested_ticker = args.ticker.strip()
    alias_entry = resolve_alias(requested_ticker)
    ticker = (alias_entry["ticker"] if alias_entry else requested_ticker).strip().upper()
    trade_date = validate_date(args.date)
    analysts = parse_analysts(args.analysts)
    config = build_config(args)

    safe_ticker = safe_ticker_component(ticker)
    report_dir = Path(config["results_dir"]) / safe_ticker / trade_date / "reports"

    if args.dry_run:
        dry_payload = {
            "ticker": ticker,
            "requested_ticker": requested_ticker,
            "alias": alias_entry,
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
            "message_log_path": str(Path(config["results_dir"]) / safe_ticker / trade_date / "message_tool.log"),
        }
        print(json.dumps(dry_payload, ensure_ascii=False, indent=2))
        return 0

    if args.clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints

        clear_all_checkpoints(config["data_cache_dir"])

    final_state, decision, stats, report_file, log_file = run_cli_equivalent_analysis(
        ticker=ticker,
        trade_date=trade_date,
        analysts=analysts,
        config=config,
    )

    payload = {
        "ticker": ticker,
        "requested_ticker": requested_ticker,
        "alias": alias_entry,
        "date": trade_date,
        "decision": decision,
        "provider": config["llm_provider"],
        "quick_model": config["quick_think_llm"],
        "deep_model": config["deep_think_llm"],
        "research_depth": args.research_depth,
        "output_language": config["output_language"],
        "report_path": str(report_file),
        "message_log_path": str(log_file),
        "stats": stats,
        "state": compact_state(final_state),
    }
    save_outputs(payload, report_dir, final_state=final_state)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "summary":
        print(render_summary(payload))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
