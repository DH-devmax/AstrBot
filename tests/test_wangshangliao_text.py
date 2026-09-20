from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from astrbot.api.message_components import At, Plain
from astrbot.builtin_stars.wangshangliao_moderation.main import Main
from astrbot.builtin_stars.wangshangliao_moderation.text import (
    PLAIN_TEXT_INSTRUCTION,
    plain_text,
    redact_reply,
)


def test_reply_redaction_preserves_management_identifiers():
    text = '密码: "test password"\n验证码：123456\nAPI Key=sk-testabcdefghijklmnop\nBearer abc.def\n电话 13812345678 邮箱 tester@example.com\nUID: 23691273 群: 1143980 操作ID: command/abc123'
    result = redact_reply(text)
    for secret in ['test password', '123456\n', 'sk-testabcdefghijklmnop', 'abc.def', '13812345678', 'tester@example.com']:
        assert secret not in result
    assert '138****5678' in result
    assert 't***@example.com' in result
    assert 'UID: 23691273 群: 1143980 操作ID: command/abc123' in result
    assert 'token=secretvalue' not in redact_reply('https://example.com/?token=secretvalue&target=1143980')
    assert 'target=1143980' in redact_reply('https://example.com/?token=secretvalue&target=1143980')
    assert redact_reply(result) == result


def test_secret_in_code_is_redacted_after_plain_text():
    result = redact_reply(plain_text('```\npassword="synthetic value"\n```'))
    assert 'synthetic value' not in result
    assert '[REDACTED]' in result


def test_markdown_plain_text():
    assert plain_text("# 标题\n\n**重点** [链接](https://example.com/a_b)") == "【标题】\n\n重点 链接 (https://example.com/a_b)"
    assert "a_b = '**keep**'" in plain_text("```python\na_b = '**keep**'\n```")
    assert plain_text("普通文本\n下一行") == "普通文本\n下一行"
    table = plain_text("| 名称 | 值 |\n| --- | --- |\n| A | 1 |")
    assert "名称" in table and "A  1" in table and "|" not in table
    assert "1. 一" in plain_text("1. 一\n2. 二")


@pytest.mark.asyncio
async def test_scoped_prompt_and_components():
    req = SimpleNamespace(system_prompt="Original persona", func_tool=None)
    mention = At(qq="123")
    result = SimpleNamespace(chain=[mention, Plain("**回答**")], is_llm_result=lambda: True, use_t2i=Mock())
    event = SimpleNamespace(get_platform_name=lambda: "wangshangliao", get_result=lambda: result,
                            get_extra=lambda _: None, is_private_chat=lambda: True, is_admin=lambda: False,
                            platform=SimpleNamespace(config={"id": "test"}))
    await Main.plain_text_request(None, event, req)
    await Main.plain_text_request(None, event, req)
    assert req.system_prompt.startswith("Original persona")
    assert req.system_prompt.count(PLAIN_TEXT_INSTRUCTION) == 1
    await Main.plain_text_result(None, event)
    assert result.chain[0] is mention
    assert result.chain[1].text == "回答"
    result.use_t2i.assert_called_once_with(False)
    event.get_platform_name = lambda: "telegram"
    result.chain[1].text = "**unchanged**"
    await Main.plain_text_result(None, event)
    assert result.chain[1].text == "**unchanged**"
