# OpenClaw Telegram Usage

This document defines how OpenClaw should translate natural-language Telegram requests into the non-interactive TradingAgents adapter.

## Goal

Allow chat requests such as:

- `分析 TSLA`
- `分析 日月光投控`
- `分析 台積電`
- `用 gpt-5.5 分析 NVDA`

OpenClaw should resolve the ticker, run the adapter, then return the `summary` output plus report paths.

## Command pattern

From the repo root:

```bash
scripts/openclaw_analyze.sh \
  --ticker <TICKER> \
  --date <YYYY-MM-DD> \
  --provider openai \
  --quick-model gpt-5.4-mini \
  --deep-model gpt-5.5 \
  --output-language 繁體中文 \
  --format summary
```

If the user does not specify a date, use today's date in the OpenClaw session timezone.

## Output paths

The adapter mirrors the repository CLI layout:

```text
~/.tradingagents/logs/<TICKER>/<DATE>/message_tool.log
~/.tradingagents/logs/<TICKER>/<DATE>/reports/complete_report.md
~/.tradingagents/logs/<TICKER>/<DATE>/reports/summary.json
~/.tradingagents/logs/<TICKER>/<DATE>/reports/chat_summary.md
```

## Ticker aliases

Resolve common Traditional Chinese names before running the adapter.

| User text | Ticker | Notes |
| --- | --- | --- |
| 台積電 / 台積 / TSMC | `2330.TW` | Taiwan Semiconductor Manufacturing |
| 日月光投控 / 日月光 / ASE | `3711.TW` | ASE Technology Holding |
| 鴻海 / 富士康 / Foxconn | `2317.TW` | Hon Hai Precision |
| 聯發科 / MTK / MediaTek | `2454.TW` | MediaTek |
| NVIDIA / 輝達 / NVDA | `NVDA` | US stock |
| Tesla / 特斯拉 / TSLA | `TSLA` | US stock |
| Apple / 蘋果 / AAPL | `AAPL` | US stock |
| Microsoft / 微軟 / MSFT | `MSFT` | US stock |
| Google / Alphabet / GOOGL | `GOOGL` | US stock |
| Amazon / 亞馬遜 / AMZN | `AMZN` | US stock |
| Meta / Facebook / META | `META` | US stock |

If a company name is not in this table, search/resolve the ticker first. Do not guess silently when multiple listed companies match.

## Chat response pattern

Return concise Traditional Chinese:

1. One-line completion status
2. `Decision: <Buy/Hold/Sell/etc>` if available
3. 3-6 bullet CEO summary
4. `complete_report.md` path
5. `message_tool.log` path when the user asks for trace/logs

## Guardrails

- Do not commit or print API keys.
- Use `.venv` through `scripts/openclaw_analyze.sh`; do not pollute system Python.
- Prefer `--format summary` for Telegram to avoid flooding the chat.
- For Taiwan tickers, mention data-source warnings if yfinance/stockstats emits parsing errors.
- If the adapter fails because of provider/model/API limits, report the blocker plainly and preserve the log path when available.
