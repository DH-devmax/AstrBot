"""Fixed moderation operations for explicit human requests, not AI tools."""

import hashlib
import json
import sqlite3
from collections.abc import Callable

from .business import BusinessClient
from .diagnostics import Diagnostics
from .directory import member_directory
from .storage import instance_dir
from .wire import ProtocolError


async def execute(
    client: BusinessClient,
    instance: str,
    account: str,
    operation: str,
    action: str,
    group: int,
    member: int = 0,
    text: str = "",
    *,
    authorize: Callable[[], None] | None = None,
) -> dict:
    """Execute a human-confirmed action once and retain ambiguous outcomes.

    Args:
        client: Authenticated business client.
        instance: Saved bot instance ID.
        account: Expected business account ID.
        operation: Stable operation ID; reuse it when querying a previous attempt.
        action: Fixed moderation action name.
        group: Positive business group ID.
        member: Member ID for member actions.
        text: Announcement content.
        authorize: Revalidate current local authorization after remote lookups.

    Returns:
        Persisted operation result, without authentication material.

    Raises:
        ProtocolError: If identity, role, arguments or operation ID conflict.
    """
    if not operation or len(operation) > 128 or type(group) is not int or group <= 0:
        raise ProtocolError("moderation_arguments")
    if str(client.fields[3]) != account:
        raise ProtocolError("moderation_identity")
    routes = {
        "kick": ("/v1/group/remove-group-member", {"groupMemberIds": [member]}),
        "mute": ("/v1/group/set-member-mute", {"userId": member, "min": 1}),
        "unmute": ("/v1/group/member-mute-cancel", {"userId": member}),
        "mute_all": ("/v1/group/set-group-mute", {"muteMode": "MUTE_MEMBER"}),
        "unmute_all": ("/v1/group/set-group-mute", {"muteMode": "MUTE_NO"}),
        "announce": (
            "/v1/group/add-notice",
            {"noticeContent": text, "noticeMode": "COMMON_NOTICE"},
        ),
    }
    if action not in routes or (
        action in {"mute", "unmute", "kick"}
        and (type(member) is not int or member <= 0)
    ):
        raise ProtocolError("moderation_arguments")
    if action == "announce" and (not text.strip() or len(text) > 2000):
        raise ProtocolError("moderation_arguments")
    route, params = routes[action]
    params = {"groupId": group, **params}
    digest = hashlib.sha256(
        json.dumps([account, route, params], sort_keys=True).encode()
    ).hexdigest()
    root = instance_dir(instance)
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "moderation.sqlite3") as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)"
        )
        row = db.execute(
            "SELECT digest,result FROM operations WHERE id=?", (operation,)
        ).fetchone()
        if row:
            if row[0] != digest:
                raise ProtocolError("moderation_operation_conflict")
            return json.loads(row[1])
    groups = await client.request("/v1/group/get-group-list", {"v": "0"})
    target = next(
        (
            g
            for g in groups.get("owner", []) + groups.get("member", [])
            if str(g.get("groupId")) == str(group)
        ),
        None,
    )
    role = (target or {}).get("me", {}).get("role")
    if role not in {"GROUP_ROLE_OWNER", "GROUP_ROLE_ADMIN"}:
        raise ProtocolError("moderation_permission")
    if action in {"mute", "unmute", "kick"}:
        page = await member_directory(client, str(group))
        matches = [
            m
            for m in page.get("groupMemberInfo", [])
            if str(m.get("userId")) == str(member)
        ]
        if (
            len(matches) != 1
            or matches[0].get("groupRole") != "GROUP_ROLE_MEMBER"
            or not matches[0].get("nimId")
        ):
            raise ProtocolError("moderation_target")
    if authorize is not None:
        authorize()
    result = {
        "operation": operation,
        "action": action,
        "group": group,
        "status": "unknown",
    }
    # Commit before the network write: interruption must never trigger a blind retry.
    with sqlite3.connect(root / "moderation.sqlite3") as db:
        try:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?)",
                (operation, digest, json.dumps(result)),
            )
        except sqlite3.IntegrityError:
            raise ProtocolError("moderation_operation_busy") from None
    try:
        receipt = await client.request(route, params)
        result["status"] = "accepted"
        if action == "announce":
            notice_id = str(receipt.get("noticeId", receipt.get("id", "")))
            notices = await client.request(
                "/v1/group/notice-list", {"groupId": group, "v": "0"}
            )
            if notice_id and any(
                str(n.get("noticeId", n.get("id", ""))) == notice_id
                and n.get("noticeContent", n.get("content")) == text
                for n in notices.get("noticeInfoList", [])
            ):
                result.update(status="verified", notice_id=notice_id)
    except Exception:
        result["status"] = "unknown"
    with sqlite3.connect(root / "moderation.sqlite3") as db:
        db.execute(
            "UPDATE operations SET result=? WHERE id=?", (json.dumps(result), operation)
        )
    Diagnostics(instance).emit("moderation", result["status"], operation)
    return result
