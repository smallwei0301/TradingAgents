import json

import pytest

from scripts import openclaw_alias
from scripts.openclaw_chat_analyze import main, parse_chat_request


@pytest.mark.unit
@pytest.mark.parametrize(
    ("message", "target", "model"),
    [
        ("分析 日月光投控", "日月光投控", None),
        ("請幫我分析 台積電", "台積電", None),
        ("用 gpt-5.5 分析 NVDA", "NVDA", "gpt-5.5"),
        ("NVDA", "NVDA", None),
        ("日月光投控", "日月光投控", None),
    ],
)
def test_parse_chat_request(message, target, model):
    assert parse_chat_request(message) == (target, model)


@pytest.mark.unit
def test_parse_chat_request_rejects_empty_message():
    with pytest.raises(SystemExit):
        parse_chat_request("   ")


@pytest.mark.unit
def test_main_persists_resolved_unknown_alias_and_runs_dry_run(tmp_path, monkeypatch):
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text('{"aliases": {}}', encoding="utf-8")
    monkeypatch.setattr(openclaw_alias, "ALIASES_PATH", alias_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "openclaw_chat_analyze.py",
            "分析 測試公司",
            "--date",
            "2026-05-07",
            "--resolved-ticker",
            "TEST.TW",
            "--canonical",
            "測試公司股份有限公司",
            "--dry-run",
        ],
    )

    assert main() == 0

    data = json.loads(alias_path.read_text(encoding="utf-8"))
    assert data["aliases"]["測試公司"]["ticker"] == "TEST.TW"
    assert data["aliases"]["測試公司"]["source"] == "llm"


@pytest.mark.unit
def test_main_rejects_unknown_chinese_alias_without_resolved_ticker(tmp_path, monkeypatch):
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text('{"aliases": {}}', encoding="utf-8")
    monkeypatch.setattr(openclaw_alias, "ALIASES_PATH", alias_path)
    monkeypatch.setattr("sys.argv", ["openclaw_chat_analyze.py", "分析 測試公司", "--dry-run"])

    with pytest.raises(SystemExit, match="Unknown alias"):
        main()
