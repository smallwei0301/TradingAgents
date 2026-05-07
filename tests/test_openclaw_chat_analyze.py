import pytest

from scripts.openclaw_chat_analyze import parse_chat_request


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
