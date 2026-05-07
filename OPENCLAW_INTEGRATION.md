# OpenClaw Integration

This fork exposes TradingAgents to OpenClaw through a thin non-interactive adapter.
The goal is to keep the TradingAgents core intact while allowing OpenClaw skills,
chat commands, and cron jobs to run stock analysis reliably.

## Files

- `scripts/openclaw_analyze.py` — OpenClaw adapter entrypoint
- `.env.openclaw.example` — environment/secrets template

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Dry-run verification

```bash
. .venv/bin/activate
python scripts/openclaw_analyze.py \
  --ticker NVDA \
  --date 2026-05-07 \
  --dry-run

python -m py_compile scripts/openclaw_analyze.py
```

## Run analysis

Prefer the wrapper; it automatically uses `.venv/bin/python` when available:

```bash
scripts/openclaw_analyze.sh \
  --ticker NVDA \
  --date 2026-05-07 \
  --provider openai \
  --quick-model gpt-5.4-mini \
  --deep-model gpt-5.4 \
  --output-language 繁體中文
```

Output reports are written to:

```text
~/.tradingagents/logs/<TICKER>/<DATE>/openclaw_report/
```

The adapter supports:

- `--format markdown|json`
- `--analysts market,social,news,fundamentals`
- `--research-depth 1`
- `--checkpoint`
- `--results-dir`, `--cache-dir`, `--memory-log-path`
- `--dry-run`

## Credentials

The adapter uses TradingAgents provider env vars. Set only the providers you use:

- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `DEEPSEEK_API_KEY`
- `GOOGLE_API_KEY`
- `ANTHROPIC_API_KEY`
- `XAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `ZHIPU_API_KEY`
- `ALPHA_VANTAGE_API_KEY` only if Alpha Vantage is enabled

Do not use Codex OAuth as a substitute for provider API keys. Codex OAuth is for
Codex CLI/app authentication, not for TradingAgents' LangChain/OpenAI SDK calls.

## OpenClaw skill

OpenClaw skill path:

```text
/root/.openclaw/skills/tradingagents-openclaw/SKILL.md
```

The skill should call this repo's adapter rather than modifying TradingAgents core.
