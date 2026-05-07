import json

import pytest

from scripts import openclaw_alias


@pytest.mark.unit
def test_resolve_seed_alias():
    entry = openclaw_alias.resolve_alias("日月光投控")

    assert entry is not None
    assert entry["ticker"] == "3711.TW"
    assert entry["canonical"] == "日月光投控"


@pytest.mark.unit
def test_add_alias_persists_alias_and_ticker(tmp_path, monkeypatch):
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text('{"aliases": {}}', encoding="utf-8")
    monkeypatch.setattr(openclaw_alias, "ALIASES_PATH", alias_path)

    entry = openclaw_alias.add_alias("測試公司", "test.tw", "測試公司股份有限公司", "llm")

    assert entry["ticker"] == "TEST.TW"
    data = json.loads(alias_path.read_text(encoding="utf-8"))
    assert data["aliases"]["測試公司"]["ticker"] == "TEST.TW"
    assert data["aliases"]["TEST.TW"]["ticker"] == "TEST.TW"
    assert openclaw_alias.resolve_alias("測試公司")["canonical"] == "測試公司股份有限公司"


@pytest.mark.unit
def test_invalid_ticker_is_rejected(tmp_path, monkeypatch):
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text('{"aliases": {}}', encoding="utf-8")
    monkeypatch.setattr(openclaw_alias, "ALIASES_PATH", alias_path)

    with pytest.raises(SystemExit):
        openclaw_alias.add_alias("壞代碼", "../../BAD", "壞代碼", "llm")
