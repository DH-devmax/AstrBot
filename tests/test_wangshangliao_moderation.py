from unittest.mock import AsyncMock

import pytest

from astrbot.core.platform.sources.wangshangliao import moderation
from astrbot.core.platform.sources.wangshangliao.wire import ProtocolError


@pytest.mark.asyncio
async def test_revocation_after_remote_lookup_prevents_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(moderation, "instance_dir", lambda _: tmp_path)
    client = AsyncMock()
    client.fields = [0, 0, 0, 12]
    client.request.return_value = {"owner": [{"groupId": 1, "me": {"role": "GROUP_ROLE_ADMIN"}}]}

    def revoked():
        raise ProtocolError("moderation_permission")

    with pytest.raises(ProtocolError, match="moderation_permission"):
        await moderation.execute(client, "bot", "12", "revoked", "mute_all", 1, authorize=revoked)
    assert client.request.await_count == 1


@pytest.mark.asyncio
async def test_moderation_dedup_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(moderation, "instance_dir", lambda _: tmp_path)
    client = AsyncMock()
    client.fields = [0, 0, 0, 12]
    client.request.side_effect = [
        {"owner": [{"groupId": 1, "me": {"role": "GROUP_ROLE_ADMIN"}}]},
        {
            "groupMemberInfo": [
                {"userId": 2, "nimId": 22, "groupRole": "GROUP_ROLE_MEMBER"}
            ]
        },
        {},
    ]
    result = await moderation.execute(client, "bot", "12", "op", "mute", 1, 2)
    assert result["status"] == "accepted"
    assert await moderation.execute(client, "bot", "12", "op", "mute", 1, 2) == result
    assert client.request.call_count == 3
    with pytest.raises(ProtocolError, match="conflict"):
        await moderation.execute(client, "bot", "12", "op", "unmute", 1, 2)


@pytest.mark.asyncio
async def test_moderation_rejects_nonadmin(tmp_path, monkeypatch):
    monkeypatch.setattr(moderation, "instance_dir", lambda _: tmp_path)
    client = AsyncMock()
    client.fields = [0, 0, 0, 12]
    client.request.return_value = {
        "member": [{"groupId": 1, "me": {"role": "GROUP_ROLE_MEMBER"}}]
    }
    with pytest.raises(ProtocolError, match="permission"):
        await moderation.execute(client, "bot", "12", "op", "mute_all", 1)
    assert client.request.call_count == 1


@pytest.mark.asyncio
async def test_moderation_unknown_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(moderation, "instance_dir", lambda _: tmp_path)
    client = AsyncMock()
    client.fields = [0, 0, 0, 12]
    client.request.side_effect = [
        {"owner": [{"groupId": 1, "me": {"role": "GROUP_ROLE_ADMIN"}}]},
        TimeoutError(),
    ]
    result = await moderation.execute(client, "bot", "12", "op", "mute_all", 1)
    assert result["status"] == "unknown"
    assert await moderation.execute(client, "bot", "12", "op", "mute_all", 1) == result
    assert client.request.call_count == 2
