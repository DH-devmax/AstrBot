"""Native Wangshangliao group text adapter; no external gateway."""

import asyncio
import json
import secrets
import sqlite3
import time
import uuid

import aiohttp

from astrbot.api.message_components import At, Plain
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
    register_platform_adapter,
)
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.platform import PlatformStatus

from . import wire
from .business import BusinessClient, BusinessError, Deployment
from .diagnostics import Diagnostics
from .directory import member_directory
from .event import WangshangliaoEvent, is_managed_account, mentioned
from .nim import NimClient, messages
from .storage import Ledger, Vault, instance_dir
from .text import plain_text, redact_reply

ACTIVE_ACCOUNTS: set[str] = set()


@register_platform_adapter("wangshangliao", "旺商聊", support_streaming_message=False)
class WangshangliaoAdapter(Platform):
    """Own one account's transport, ledger and sequential group workers."""

    supports_operation_ids = True

    def __init__(self, platform_config, platform_settings, event_queue):
        super().__init__(platform_config, event_queue)
        self.diagnostics = Diagnostics(platform_config["id"])
        self.account = str(platform_config.get("account_id", ""))
        self.enabled_groups = set(platform_config.get("enabled_groups", []))
        self.vault = Vault(platform_config["id"])
        self.ledger = Ledger(instance_dir(platform_config["id"]) / "messages.sqlite3")
        self.stopping = asyncio.Event()
        self.send_lock = asyncio.Lock()
        self.nim = None
        self.business = None
        self.http = None
        self.nim_account = ""
        self.groups = {}
        self.members = {}
        self.group_directory_state = {}
        self.member_refresh_locks = {}
        self.member_refresh_at = {}
        self.workers = {}
        self.events = set()
        self.connection_state = "stopped"
        self.runner = None
        self.heartbeat_task = None
        self.unsupported_pushes = 0
        self.current_error = ""
        self.last_connected_at = None
        self.next_retry_at = None
        self.test_window = None

    def meta(self) -> PlatformMetadata:
        """Expose the saved instance ID, never an account-global platform ID."""
        return PlatformMetadata(
            "wangshangliao",
            "旺商聊",
            self.config["id"],
            support_streaming_message=False,
            support_proactive_message=True,
        )

    def get_stats(self) -> dict:
        """Expose authentication and connection state separately."""
        return {
            **super().get_stats(),
            "status": {
                "online": "running",
                "rate_limited": "pending",
                "account_conflict": "error",
                "reconnecting": "pending",
                "reauth_required": "error",
                "error": "error",
                "stopped": "stopped",
            }[self.connection_state],
            "connection_state": self.connection_state,
            "unsupported_pushes": self.unsupported_pushes,
            "current_error": self.current_error,
            "last_connected_at": self.last_connected_at,
            "next_retry_at": self.next_retry_at,
            "group_directory_state": dict(self.group_directory_state),
        }

    async def run(self) -> None:
        """Restore a saved session and reconnect transport without password retries."""
        self.runner = asyncio.current_task()
        claimed = False
        try:
            if not self.account or self.account in ACTIVE_ACCOUNTS:
                raise wire.ProtocolError("account_already_active")
            ACTIVE_ACCOUNTS.add(self.account)
            claimed = True
            deployment = Deployment.load()
            if not deployment.message_key.get_secret_value():
                raise wire.ProtocolError("message_key_missing")
            saved = self.vault.load()
            if not saved or str(saved["business"]["uid"]) != self.account:
                raise wire.ProtocolError("reauth_required")
            self.http = aiohttp.ClientSession()
            self.business = BusinessClient(deployment, self.http)
            self.business.restore(saved["business"])
            self.diagnostics.emit("session", "restored")
            self.nim_account = saved["nim_id"]
            await self.ledger.open()
            delay = 1
            while not self.stopping.is_set():
                self.connection_state = "reconnecting"
                self.next_retry_at = None
                retry_wait = min(30, delay * (1 + secrets.randbelow(251) / 1000))
                try:
                    refreshed = await self.business.request("/v1/user/RefreshToken", {})
                    token = refreshed.get("nimToken")
                    if not isinstance(token, str) or not token:
                        raise wire.ProtocolError("refresh_shape")
                    saved["nim_token"] = token
                    self.vault.save(saved)
                    await self.load_groups()
                    self.nim = NimClient(self.http)
                    await self.nim.connect(deployment, saved["nim_id"], token)
                    async with self.ledger.db.execute(
                        "SELECT cursor FROM sync WHERE account=?", (self.account,)
                    ) as cursor:
                        row = await cursor.fetchone()
                    # Sync responses may precede queued pushes; persist their watermark only
                    # after the single push consumer has committed all earlier events.
                    code, body = await self.nim.request(
                        5,
                        1,
                        wire.properties(
                            [
                                (2, (row[0] if row else "0").encode()),
                                (7, (row[0] if row else "0").encode()),
                            ]
                        ),
                    )
                    if code != 200 or len(body) != 8:
                        raise wire.ProtocolError("sync_boundary")
                    self.nim.pushes.put_nowait((5, 1, 0, 200, body))
                    self.heartbeat_task = asyncio.create_task(self.keep_alive())
                    self.diagnostics.emit("connection", "online")
                    self.connection_state = "online"
                    self.current_error = ""
                    self.last_connected_at = time.time()
                    self.status = PlatformStatus.RUNNING
                    delay = 1
                    async with self.ledger.db.execute(
                        "SELECT DISTINCT team FROM inbox WHERE account=? AND team LIKE 'private/%' AND state='pending'",
                        (self.account,),
                    ) as cursor:
                        private_sessions = [row[0] for row in await cursor.fetchall()]
                    for team in private_sessions:
                        if team not in self.workers or self.workers[team].done():
                            self.workers[team] = asyncio.create_task(
                                self.process_group(team)
                            )
                    for team in self.enabled_groups:
                        if team in self.groups and (
                            team not in self.workers or self.workers[team].done()
                        ):
                            self.workers[team] = asyncio.create_task(
                                self.process_group(team)
                            )
                    while not self.stopping.is_set() and not self.nim.closed.is_set():
                        try:
                            packet = await asyncio.wait_for(self.nim.pushes.get(), 15)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            incoming, boundary = messages(packet)
                        except wire.ProtocolError as exc:
                            # A malformed or unsupported push must not tear down a healthy
                            # socket; request/ACK traffic can continue after diagnostics.
                            if str(exc) in {
                                "message_fields",
                                "message_trailing",
                                "notification",
                                "message_count",
                            }:
                                self.unsupported_pushes += 1
                                self.diagnostics.emit(
                                    "receive",
                                    "unsupported",
                                    failed=True,
                                    error=str(exc),
                                )
                                continue
                            raise
                        if not incoming and boundary is None:
                            self.unsupported_pushes += 1
                        for message in incoming:
                            try:
                                await self.ingest(message)
                            except wire.ProtocolError as exc:
                                if str(exc) != "message_decode":
                                    raise
                                self.unsupported_pushes += 1
                                self.diagnostics.emit(
                                    "receive",
                                    "unsupported",
                                    message.get(12, ""),
                                    failed=True,
                                    error="message_decode",
                                )
                                await self.nim.acknowledge(int(message[0]), message[12])
                        if boundary is not None:
                            await self.ledger.db.execute(
                                "INSERT INTO sync VALUES(?,?) ON CONFLICT(account) DO UPDATE SET cursor=excluded.cursor",
                                (self.account, str(boundary)),
                            )
                            await self.ledger.db.commit()
                    if self.nim.closed.is_set():
                        raise wire.ProtocolError(self.nim.error)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    label = (
                        str(exc)
                        if isinstance(exc, wire.ProtocolError)
                        else "connection_failed"
                    )
                    self.current_error = label
                    if label in {"reauth_required", "account_conflict", "nim_kicked"}:
                        raise wire.ProtocolError(label) from None
                    self.diagnostics.emit(
                        "connection",
                        "rate_limited"
                        if label == "rate_limited"
                        else "retry_scheduled",
                        failed=True,
                        error=label,
                    )
                    self.connection_state = "reconnecting"
                    if isinstance(exc, BusinessError) and label == "rate_limited":
                        self.connection_state = "rate_limited"
                        retry_wait = max(retry_wait, exc.retry_after)
                finally:
                    if self.heartbeat_task:
                        self.heartbeat_task.cancel()
                        await asyncio.gather(
                            self.heartbeat_task, return_exceptions=True
                        )
                    if self.nim:
                        await self.nim.close()
                try:
                    self.next_retry_at = time.time() + retry_wait
                    await asyncio.wait_for(self.stopping.wait(), retry_wait)
                except asyncio.TimeoutError:
                    delay = min(delay * 2, 30)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.current_error = (
                str(exc) if isinstance(exc, wire.ProtocolError) else "startup_failed"
            )
            self.next_retry_at = None
            self.connection_state = (
                "reauth_required"
                if str(exc) == "reauth_required"
                else "account_conflict"
                if str(exc) == "account_conflict"
                else "error"
            )
            self.diagnostics.emit(
                "connection",
                self.connection_state,
                failed=True,
                terminal=True,
                error=self.current_error,
            )
            self.record_error(
                str(exc) if isinstance(exc, wire.ProtocolError) else "startup_failed"
            )
        finally:
            self.stopping.set()
            pipeline_tasks = []
            for event in self.events:
                event.processing_completion.cancel()
                task = getattr(event, "processing_task", None)
                if isinstance(task, asyncio.Task):
                    task.cancel()
                    pipeline_tasks.append(task)
            await asyncio.gather(*pipeline_tasks, return_exceptions=True)
            for task in self.workers.values():
                task.cancel()
            await asyncio.gather(*self.workers.values(), return_exceptions=True)
            if self.nim:
                await self.nim.close()
            if self.http:
                await self.http.close()
            await self.ledger.close()
            self.diagnostics.emit("connection", "stopped")
            if claimed:
                ACTIVE_ACCOUNTS.discard(self.account)

    async def keep_alive(self) -> None:
        """Maintain heartbeat independently of push traffic and model processing."""
        try:
            while not self.stopping.is_set():
                await asyncio.sleep(15)
                await self.nim.heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.nim.close()

    async def load_groups(self) -> None:
        """Load explicit business-to-NIM identities for enabled groups only."""
        data = await self.business.request("/v1/group/get-group-list", {"v": "0"})
        if not isinstance(data, dict) or any(
            not isinstance(data.get(key), list) for key in ("owner", "member")
        ):
            raise wire.ProtocolError("groups_shape")
        groups = {}
        for entry in data.get("owner", []) + data.get("member", []):
            group_id, team = str(entry["groupId"]), str(entry["groupCloudId"])
            if group_id in self.enabled_groups:
                if (
                    (group_id in groups and groups[group_id] != team)
                    or not team.isascii()
                    or not team.isdigit()
                ):
                    raise wire.ProtocolError("group_identity")
                groups[group_id] = team
        self.groups = groups
        self.members = {}
        self.group_directory_state = {}
        for group_id in groups:
            try:
                await self.refresh_member_mapping(group_id)
            except (wire.ProtocolError, aiohttp.ClientError, TimeoutError) as exc:
                if str(exc) in {"reauth_required", "account_conflict"}:
                    raise
                self.diagnostics.emit(
                    "directory",
                    "unavailable",
                    group_id,
                    failed=True,
                    error="member_directory_unavailable",
                )

    async def refresh_member_mapping(
        self, group: str, *, bounded: bool = False
    ) -> dict | None:
        """Publish a complete roster atomically, coalescing ingress refreshes.

        Args:
            group: Enabled business group ID.
            bounded: Limit mismatch-triggered requests to one per thirty seconds.

        Returns:
            Validated roster, or None when a bounded refresh is throttled.

        Raises:
            ProtocolError: If the roster cannot establish consistent identities.
        """
        lock = self.member_refresh_locks.setdefault(group, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if bounded and now - self.member_refresh_at.get(group, float("-inf")) < 30:
                return None
            self.member_refresh_at[group] = now
            try:
                page = await member_directory(self.business, group)
                mapping = {
                    row["userId"]: row["nimId"] for row in page["groupMemberInfo"]
                }
                if not page.get("complete") or (
                    self.nim_account
                    and self.account in mapping
                    and mapping[self.account] != self.nim_account
                ):
                    raise wire.ProtocolError("member_identity")
            except (wire.ProtocolError, aiohttp.ClientError, TimeoutError):
                self.group_directory_state[group] = {
                    "complete": False,
                    "error": "member_directory_unavailable",
                    "updated_at": time.time(),
                }
                raise
            self.members[group] = mapping
            self.group_directory_state[group] = {
                "complete": True,
                "error": "",
                "updated_at": time.time(),
            }
            return page

    async def ingest(self, outer: dict) -> None:
        """Authenticate custom group text, commit its inbox, then ACK its NIM ID."""
        if outer.get(8) == "100":
            try:
                wire.open_message(
                    self.business.deployment.key("message_key"), outer.get(10, "")
                )
            except wire.ProtocolError as exc:
                if str(exc) != "message_decode":
                    raise
                # Persist only routing metadata, never unverified content. This
                # prevents poison history from repeatedly reconnecting the socket.
                target = "unsupported/" + outer[0] + "/" + outer[1]
                await self.ledger.ingest(self.account, target, outer[12], {})
                await self.ledger.mark(self.account, target, outer[12], "unsupported")
                self.unsupported_pushes += 1
                self.diagnostics.emit(
                    "receive",
                    "unsupported",
                    outer[12],
                    failed=True,
                    error="message_decode",
                )
                await self.nim.acknowledge(int(outer[0]), outer[12])
                return
        self.diagnostics.emit("receive", "received", str(outer.get(12, "")))
        if outer[0] == "0":
            if (
                not self.nim_account
                or outer[1] != self.nim_account
                or outer[2] == self.nim_account
            ):
                return
            if outer[8] != "100":
                self.unsupported_pushes += 1
                await self.nim.acknowledge(0, outer[12])
                return
            inner = wire.open_message(
                self.business.deployment.key("message_key"), outer.get(10, "")
            )
            if (
                inner.session != 1
                or str(inner.target.id) != self.account
                or str(inner.sender.id) == self.account
            ):
                raise wire.ProtocolError("private_message_identity")
            # Keep both authenticated application identity and transport peer in the
            # session key. Never infer a NIM ID from a business user ID.
            peer = outer[2]
            if not peer or len(peer.encode()) > 1024:
                raise wire.ProtocolError("private_peer")
            session = f"private/{inner.sender.id}/{wire.b64(peer.encode())}"
            supported = inner.format == 0 and (
                inner.HasField("content") or inner.mentions.HasField("content")
            )
            payload = {
                "text": inner.content.data
                if inner.HasField("content")
                else inner.mentions.content.data,
                "sender": str(inner.sender.id),
                "name": inner.sender.name,
                "created_at": inner.created_at,
                "mentions": [],
            }
            await self.ledger.ingest(self.account, session, outer[12], payload)
            if not supported:
                async with self.ledger.db.execute(
                    "UPDATE inbox SET payload=? WHERE account=? AND team=? AND message=?",
                    (
                        json.dumps(
                            {"format": inner.format, "reason": "unsupported_format"}
                        ),
                        self.account,
                        session,
                        outer[12],
                    ),
                ):
                    pass
                await self.ledger.mark(self.account, session, outer[12], "unsupported")
            await self.nim.acknowledge(0, outer[12])
            if session not in self.workers or self.workers[session].done():
                self.workers[session] = asyncio.create_task(self.process_group(session))
            return
        if outer[0] != "1":
            return
        group = next(
            (group for group, team in self.groups.items() if team == outer[1]), None
        )
        if group is None:
            return
        state = "unsupported"
        payload = {}
        if outer[8] == "100":
            inner = wire.open_message(
                self.business.deployment.key("message_key"), outer.get(10, "")
            )
            if (
                inner.session == 2
                and str(inner.target.id) == group
                and self.members.get(group, {}).get(str(inner.sender.id)) != outer[2]
            ):
                try:
                    await self.refresh_member_mapping(group, bounded=True)
                except (wire.ProtocolError, aiohttp.ClientError, TimeoutError):
                    pass
            if (
                inner.session != 2
                or str(inner.target.id) != group
                or self.members.get(group, {}).get(str(inner.sender.id)) != outer[2]
            ):
                # Removed members may still occur in reconnect history. Reject the
                # message without turning a stale mapping into a reconnect loop.
                await self.ledger.db.execute(
                    "INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,'rejected_identity')",
                    (self.account, group, outer[12], "{}"),
                )
                await self.ledger.db.commit()
                self.diagnostics.emit(
                    "receive",
                    "rejected_identity",
                    outer[12],
                    failed=True,
                    error="message_identity",
                )
                await self.nim.acknowledge(1, outer[12])
                return
            if str(inner.sender.id) == self.account:
                state = "self"
            elif inner.format == 0 and (
                inner.HasField("content") or inner.mentions.HasField("content")
            ):
                state = "pending"
                payload = {
                    "text": inner.content.data
                    if inner.HasField("content")
                    else inner.mentions.content.data,
                    "sender": str(inner.sender.id),
                    "name": inner.sender.name,
                    "created_at": inner.created_at,
                    "mentions": [str(person.uid) for person in inner.mentions.people],
                    "mention_spans": [
                        {
                            "uid": str(person.uid),
                            "nick": person.nick,
                            "start": person.start,
                            "end": person.end,
                        }
                        for person in inner.mentions.people
                    ],
                    "recall_route": {
                        "client": outer.get(11, ""),
                        "time": outer.get(7, ""),
                        "peer": outer[2],
                    },
                }
        await self.ledger.ingest(self.account, group, outer[12], payload)
        if state != "pending":
            await self.ledger.mark(self.account, group, outer[12], state)
        await self.nim.acknowledge(1, outer[12])

    async def process_group(self, group: str) -> None:
        """Await completion, including sends, before dispatching the next group event."""
        while not self.stopping.is_set():
            async with self.ledger.db.execute(
                "SELECT message,payload FROM inbox WHERE account=? AND team=? AND state='pending' ORDER BY rowid LIMIT 1",
                (self.account, group),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None or self.connection_state != "online":
                try:
                    await asyncio.wait_for(self.stopping.wait(), 0.25)
                except asyncio.TimeoutError:
                    pass
                continue
            mid, encoded = row
            try:
                payload = json.loads(encoded)
                if (
                    isinstance(payload, dict)
                    and not self.test_window
                    and is_managed_account(str(payload.get("sender", "")))
                ):
                    await self.ledger.mark(self.account, group, mid, "ignored_bot")
                    self.diagnostics.emit("process", "ignored_bot", mid)
                    continue
                if (
                    not isinstance(payload, dict)
                    or not all(
                        key in payload
                        for key in ("sender", "name", "text", "created_at", "mentions")
                    )
                    or not isinstance(payload["text"], str)
                    or not isinstance(payload["created_at"], (int, float))
                ):
                    raise ValueError("invalid_inbox_payload")
            except (ValueError, TypeError):
                await self.ledger.mark(self.account, group, mid, "needs_review")
                self.diagnostics.emit("process", "invalid_payload", mid, failed=True)
                continue
            test_scope = (
                self.test_window.admit(group, mid, payload) if self.test_window else ""
            )
            if is_managed_account(str(payload.get("sender", ""))) and not test_scope:
                await self.ledger.mark(self.account, group, mid, "ignored_bot")
                self.diagnostics.emit("process", "ignored_bot", mid)
                continue
            await self.ledger.mark(self.account, group, mid, "processing")
            message = AstrBotMessage()
            private = group.startswith("private/")
            message.type = (
                MessageType.FRIEND_MESSAGE if private else MessageType.GROUP_MESSAGE
            )
            message.self_id = self.account
            message.session_id = f"{self.account}/{group}"
            message.group_id = "" if private else group
            message.message_id = mid
            message.sender = MessageMember(payload["sender"], payload["name"])
            message.message_str = payload["text"]
            message.timestamp = payload["created_at"] // 1000
            message.raw_message = {"message_id": mid}
            eligible = private or mentioned(
                payload["text"], str(self.nim_account or ""), payload["mentions"]
            )
            message.message = (
                [At(qq=self.account)] if eligible and not private else []
            ) + [Plain(payload["text"])]
            if not private:
                reverse = {}
                for business_id, peer in self.members.get(group, {}).items():
                    reverse.setdefault(str(peer), []).append(business_id)
                mapped = [At(qq=self.account)] if eligible else []
                for peer in dict.fromkeys(payload.get("mentions", [])):
                    if str(peer) == str(self.nim_account):
                        continue
                    identities = reverse.get(str(peer), [])
                    if len(identities) == 1:
                        mapped.append(At(qq=identities[0]))
                # Only remove a verified leading self-mention for command parsing.
                encoded_text = payload["text"].encode("utf-16-le")
                for span in payload.get("mention_spans", []):
                    end = span.get("end", 0)
                    if (
                        span.get("uid") == str(self.nim_account)
                        and span.get("start") == 0
                        and type(end) is int
                        and 0 < end * 2 <= len(encoded_text)
                    ):
                        prefix = encoded_text[: end * 2].decode(
                            "utf-16-le", errors="replace"
                        )
                        remainder = (
                            encoded_text[end * 2 :]
                            .decode("utf-16-le", errors="replace")
                            .lstrip()
                        )
                        if prefix.rstrip() == "@" + span.get(
                            "nick", ""
                        ) and remainder.startswith("/群管"):
                            message.message_str = remainder
                            break
                message.message = mapped + [Plain(message.message_str)]
            event = WangshangliaoEvent(message, self, eligible)
            event.set_extra("wangshangliao_payload", payload)
            event.set_extra("wsl_test_scope", test_scope)
            if test_scope == "group_rules":
                event.set_extra("_context_only", True)
            self.events.add(event)
            self.diagnostics.emit("process", "started", mid)
            try:
                await self._event_queue.put(event)
                await event.processing_completion
                await self.ledger.mark(self.account, group, mid, "processed")
                self.diagnostics.emit("process", "completed", mid)
            except asyncio.CancelledError:
                event.processing_completion.cancel()
                await self.ledger.mark(self.account, group, mid, "needs_review")
                raise
            except Exception:
                event.processing_completion.cancel()
                await self.ledger.mark(self.account, group, mid, "needs_review")
                self.record_error("event_requires_review")
                self.diagnostics.emit(
                    "process", "needs_review", mid, failed=True, terminal=True
                )
            finally:
                self.events.discard(event)

    async def get_moderation_members(self, group: str) -> dict:
        """Fetch authenticated members for moderation identity checks.

        Args:
            group: Enabled business group ID.

        Returns:
            Platform member directory.

        Raises:
            ProtocolError: If the group is not enabled or the connection is offline.
        """
        if self.connection_state != "online" or group not in self.config.get(
            "enabled_groups", []
        ):
            raise wire.ProtocolError("moderation_identity")
        return await self.refresh_member_mapping(group)

    async def get_moderation_result(self, operation: str, group: str) -> dict:
        """Read an instance-scoped operation without creating storage.

        Args:
            operation: Exact operation identifier.
            group: Expected business group ID.

        Returns:
            Matching saved result, or an empty dictionary if unavailable.
        """
        path = instance_dir(self.config["id"]) / "moderation.sqlite3"
        if not path.is_file():
            return {}
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operations'"
            ).fetchone():
                return {}
            row = db.execute(
                "SELECT result FROM operations WHERE id=?", (operation,)
            ).fetchone()
        result = json.loads(row[0]) if row else {}
        return result if str(result.get("group")) == str(group) else {}

    async def execute_moderation(
        self, operation: str, action: str, group: int, member: int = 0, text: str = ""
    ) -> dict:
        """Execute a fixed action using the persistent operation ledger.

        Args:
            operation: Stable operation ID.
            action: Fixed supported action.
            group: Business group ID.
            member: Business target member ID.
            text: Announcement content.

        Returns:
            Accepted, verified or unknown operation result.

        Raises:
            ProtocolError: If the connection, identity or platform role is invalid.
        """
        from .moderation import execute
        from .policy import authorize_action

        authorize_action(self.config, str(group), action)
        await self.get_moderation_members(str(group))
        if self.stopping.is_set():
            raise wire.ProtocolError("not_online")
        authorize_action(self.config, str(group), action)
        return await execute(
            self.business,
            self.config["id"],
            self.account,
            operation,
            action,
            group,
            member,
            text,
            authorize=lambda: authorize_action(
                self.config if not self.stopping.is_set() else {"enable": False},
                str(group),
                action,
            ),
        )

    async def rename_member(
        self,
        operation: str,
        group: int,
        member: int,
        name: str,
        expected_card: str,
        expected_nim: str,
        *,
        authorize=None,
    ) -> dict:
        """Rename one verified ordinary member using a frozen preview.

        Args:
            operation: Stable persisted operation ID.
            group: Enabled business group ID.
            member: Verified business member ID.
            name: Proposed group card.
            expected_card: Card captured during preview.
            expected_nim: Transport identity captured during preview.
            authorize: Optional job cancellation and lifecycle check.

        Returns:
            Persisted accepted, verified or unknown outcome.

        Raises:
            ProtocolError: If the preview, lifecycle or authorization changed.
        """
        from .moderation import execute
        from .policy import authorize_action

        account, business = self.account, self.business

        def check():
            if (
                self.stopping.is_set()
                or self.connection_state != "online"
                or self.account != account
                or self.business is not business
            ):
                raise wire.ProtocolError("not_online")
            authorize_action(self.config, str(group), "rename")
            if authorize is not None:
                authorize()

        async with self.send_lock:
            check()
            return await execute(
                business,
                self.config["id"],
                account,
                operation,
                "rename",
                group,
                member,
                name,
                authorize=check,
                expected_card=expected_card,
                expected_nim=expected_nim,
            )

    async def mute_member(self, operation: str, group: int, member: int) -> dict:
        """Execute the fixed mute capability."""
        return await self.execute_moderation(operation, "mute", group, member=member)

    async def cleanup_member(
        self, operation, group, member, expected_nim, *, authorize=None
    ):
        """Remove a currently banned or cancelled ordinary member.

        Args:
            operation: Persisted operation ID.
            group: Explicitly authorized group ID.
            member: Previewed business member ID.
            expected_nim: Previewed transport identity.
            authorize: Job cancellation check invoked immediately before mutation.

        Returns:
            Persisted platform outcome, with readback when available.

        Raises:
            ProtocolError: If authorization, identity or lifecycle changed.
        """
        from .moderation import execute
        from .policy import authorize_action

        account, business = self.account, self.business

        def check():
            if (
                self.stopping.is_set()
                or self.connection_state != "online"
                or self.account != account
                or self.business is not business
            ):
                raise wire.ProtocolError("not_online")
            authorize_action(self.config, str(group), "cleanup")
            if authorize is not None:
                authorize()

        async with self.send_lock:
            check()
            return await execute(
                business,
                self.config["id"],
                account,
                operation,
                "cleanup",
                group,
                member,
                authorize=check,
                expected_nim=expected_nim,
            )

    async def unmute_member(self, operation: str, group: int, member: int) -> dict:
        """Execute the fixed unmute capability."""
        return await self.execute_moderation(operation, "unmute", group, member=member)

    async def mute_all(self, operation: str, group: int) -> dict:
        """Execute the fixed mute_all capability."""
        return await self.execute_moderation(operation, "mute_all", group)

    async def unmute_all(self, operation: str, group: int) -> dict:
        """Execute the fixed unmute_all capability."""
        return await self.execute_moderation(operation, "unmute_all", group)

    async def announce(self, operation: str, group: int, text: str) -> dict:
        """Execute the fixed announce capability."""
        return await self.execute_moderation(operation, "announce", group, text=text)

    async def recall_violation(self, group: str, mid: str, sender: str) -> str:
        """Recall a stored violation once, without retrying ambiguous results.

        Args:
            group: Enabled business group ID.
            mid: Stored server message ID.
            sender: Expected business sender ID.

        Returns:
            Accepted, rejected, or unknown transport status.

        Raises:
            ProtocolError: If authorization, roles or stored routing are invalid.
        """
        from .policy import authorize_action

        authorize_action(self.config, group, "recall")
        roster = (await self.get_moderation_members(group))["groupMemberInfo"]
        roles = {str(m["userId"]): m.get("groupRole") for m in roster}
        if (
            roles.get(self.account) not in {"GROUP_ROLE_OWNER", "GROUP_ROLE_ADMIN"}
            or roles.get(sender) != "GROUP_ROLE_MEMBER"
        ):
            raise wire.ProtocolError("moderation_permission")
        async with self.ledger.db.execute(
            "SELECT payload FROM inbox WHERE account=? AND team=? AND message=?",
            (self.account, group, mid),
        ) as cursor:
            row = await cursor.fetchone()
        data = json.loads(row[0]) if row else {}
        route = data.get("recall_route", {})
        if (
            data.get("sender") != sender
            or not route.get("client")
            or not str(route.get("time", "")).isdigit()
            or int(route["time"]) <= 0
            or not mid.isdigit()
            or int(mid) <= 0
            or route.get("peer") != self.members.get(group, {}).get(sender)
        ):
            raise wire.ProtocolError("recall_identity")
        async with self.send_lock:
            authorize_action(self.config, group, "recall")
            if self.stopping.is_set() or self.connection_state != "online":
                raise wire.ProtocolError("not_online")
            key = f"recall/{self.account}/{group}/{mid}"
            _, state = await self.ledger.reserve(key, json.dumps(route, sort_keys=True))
            if state != "new":
                return state
            try:
                authorize_action(self.config, group, "recall")
                if self.stopping.is_set() or self.connection_state != "online":
                    raise wire.ProtocolError("not_online")
            except wire.ProtocolError:
                await self.ledger.finish(key, "rejected")
                raise
            try:
                code, _ = await self.nim.request(
                    7,
                    13,
                    wire.properties(
                        [
                            (0, str(route["time"]).encode()),
                            (1, b"8"),
                            (2, self.groups[group].encode()),
                            (3, route["peer"].encode()),
                            (10, route["client"].encode()),
                            (11, mid.encode()),
                            (16, route["peer"].encode()),
                        ]
                    ),
                )
                result = "accepted" if code == 200 else "rejected"
            except BaseException:
                await self.ledger.finish(key, "unknown")
                raise
            await self.ledger.finish(key, result)
            self.diagnostics.emit("recall", result, mid)
            return result

    async def send_text(
        self,
        group: str,
        key: str,
        text: str,
        *,
        mentions=None,
        test_mid=None,
        proactive=False,
    ) -> str:
        """Persist intent before transport; uncertain sends are query-only."""
        async with self.send_lock:
            private = group.startswith("private/")
            if proactive and (
                not self.config.get("enable", True)
                or not self.config.get("proactive_send", {}).get("enabled", False)
                or group not in self.config.get("proactive_send", {}).get("targets", [])
            ):
                raise wire.ProtocolError("proactive_not_authorized")
            if (
                self.stopping.is_set()
                or self.connection_state != "online"
                or (not private and group not in self.groups)
            ):
                raise wire.ProtocolError("not_online")
            if private:
                test_reply = bool(
                    test_mid
                    and self.test_window
                    and self.test_window.reply(
                        group, test_mid, key.rsplit("/part/", 1)[0]
                    )
                )
                if (
                    is_managed_account(group.split("/", 2)[1])
                    and not test_reply
                    and not (
                        (window := getattr(self, "test_command_window", None))
                        and window.send_command(self, group, text, key, consume=True)
                    )
                ):
                    raise wire.ProtocolError("managed_bot_peer")
                async with self.ledger.db.execute(
                    "SELECT 1 FROM inbox WHERE account=? AND team=? LIMIT 1",
                    (self.account, group),
                ) as cursor:
                    if await cursor.fetchone() is None:
                        raise wire.ProtocolError("private_peer_unknown")
                _, target, encoded_peer = group.split("/", 2)
                transport_target = wire.unb64(encoded_peer, 1024).decode()
            else:
                target, transport_target = group, self.groups[group]
            if not text or len(text.encode()) > 4096:
                raise wire.ProtocolError("text_limit")
            fingerprint = json.dumps([group, text, mentions], ensure_ascii=True)
            nonce, state = await self.ledger.reserve(key, fingerprint)
            if state != "new":
                self.diagnostics.emit("send", "existing_intent", key)
                return state
            self.diagnostics.emit("send", "reserved", key)
            client_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{self.config['id']}/{key}")
            )
            inner = wire.ApplicationMessage(
                sender=wire.Source(id=int(self.account)),
                target=wire.Source(id=int(target)),
                created_at=int(time.time() * 1000),
                device=1,
                session=1 if private else 2,
                version=2,
                format=0,
                client_id=client_id,
                content=wire.Content(data=text),
            )
            if mentions:
                if private:
                    raise wire.ProtocolError("group_mentions_only")
                inner.ClearField("content")
                inner.mentions.content.data = text
                for person in mentions:
                    inner.mentions.people.add(**person)
            if (
                self.stopping.is_set()
                or self.connection_state != "online"
                or (
                    proactive
                    and (
                        not self.config.get("enable", True)
                        or not self.config.get("proactive_send", {}).get(
                            "enabled", False
                        )
                        or group
                        not in self.config.get("proactive_send", {}).get("targets", [])
                    )
                )
            ):
                await self.ledger.finish(key, "rejected")
                return "rejected"
            try:
                attachment = wire.seal_message(
                    self.business.deployment.key("message_key"),
                    inner,
                    int(nonce),
                    secrets.randbits(64) or 1,
                    int(time.time()),
                )
                code, body = await self.nim.request(
                    7 if private else 8,
                    1 if private else 2,
                    wire.properties(
                        [
                            (0, b"0" if private else b"1"),
                            (1, transport_target.encode()),
                            (8, b"100"),
                            (10, attachment.encode()),
                            (11, client_id.encode()),
                        ]
                    ),
                )
                if code != 200:
                    await self.ledger.finish(key, "rejected")
                    self.diagnostics.emit("send", "rejected", key, failed=True)
                    return "rejected"
                receipt, end = wire.read_properties(body)
                if (
                    end != len(body)
                    or not receipt.get(12)
                    or not receipt.get(7, b"").isdigit()
                    or receipt.get(11, client_id.encode()) != client_id.encode()
                ):
                    raise wire.ProtocolError("receipt_shape")
                await self.ledger.finish(key, "accepted", receipt[12].decode())
                self.diagnostics.emit("send", "accepted", key)
                return "accepted"
            except BaseException:
                await self.ledger.finish(key, "unknown")
                self.diagnostics.emit(
                    "send", "unknown", key, failed=True, terminal=True
                )
                raise

    async def send_reply_text(
        self, group, key, text, *, mentions=None, test_mid=None, proactive=False
    ):
        """Send a bounded logical reply with stable, non-overlapping segments.

        Args:
            group: Verified native target.
            key: Stable logical operation identifier.
            text: Formatted reply text.
            mentions: UTF-16 mention ranges.
            test_mid: Correlated developer-window inbound message.
            proactive: Require explicit target authorization.

        Returns:
            Durable logical operation status.
        """
        fingerprint = json.dumps([group, text, mentions], ensure_ascii=True)
        async with self.send_lock:
            _, state = await self.ledger.reserve(key, fingerprint)
        if state != "new":
            return "unknown" if state == "sending" else state
        offset = 0
        try:
            while text:
                end = 0
                size = 0
                units = 0
                for char in text:
                    if size + len(char.encode()) > 4096:
                        break
                    end += 1
                    size += len(char.encode())
                    units += len(char.encode("utf-16-le")) // 2
                for mention in mentions or []:
                    if mention["start"] < offset + units < mention["end"]:
                        units = mention["start"] - offset
                        end = len(
                            text.encode("utf-16-le")[: units * 2].decode("utf-16-le")
                        )
                if not end:
                    raise wire.ProtocolError("mention_text_limit")
                part_mentions = [
                    {**m, "start": m["start"] - offset, "end": m["end"] - offset}
                    for m in mentions or []
                    if offset <= m["start"] and m["end"] <= offset + units
                ]
                result = await self.send_text(
                    group,
                    f"{key}/part/{offset}",
                    text[:end],
                    mentions=part_mentions or None,
                    test_mid=test_mid,
                    proactive=proactive,
                )
                if result not in {"accepted", "verified"}:
                    await self.ledger.finish(key, result)
                    return result
                text = text[end:]
                offset += units
            child = await self.ledger.receipt(f"{key}/part/0")
            await self.ledger.finish(
                key, "accepted", child.get("server_id", "") if child else ""
            )
            return "accepted"
        except BaseException:
            await self.ledger.finish(key, "unknown")
            raise

    async def send_by_session(
        self, session: MessageSession, message_chain, *, operation_id: str | None = None
    ) -> dict:
        """Send an explicitly authorized text message to one known session.

        Args:
            session: Target platform session.
            message_chain: AstrBot message chain containing text components.

        Raises:
            ProtocolError: If proactive sending is disabled or the target is invalid.
        """
        if not self.config.get("proactive_send", {}).get("enabled", False):
            raise wire.ProtocolError("proactive_not_authorized")
        if session.platform_id != self.config["id"]:
            raise wire.ProtocolError("session_platform")
        if session.message_type is MessageType.GROUP_MESSAGE:
            target = session.session_id.split("/", 1)[-1]
            if target not in self.groups or target not in self.config.get(
                "enabled_groups", []
            ):
                raise wire.ProtocolError("session_target")
        elif session.message_type is MessageType.FRIEND_MESSAGE:
            target = session.session_id.removeprefix(f"{self.account}/")
            if not target.startswith("private/") or len(target.split("/")) != 3:
                raise wire.ProtocolError("session_target")
        else:
            raise wire.ProtocolError("session_type")
        parts = getattr(message_chain, "chain", [])
        if not parts or any(not isinstance(part, (Plain, At)) for part in parts):
            raise wire.ProtocolError("text_only")
        text = ""
        people = []
        for part in parts:
            if isinstance(part, Plain):
                text += redact_reply(plain_text(part.text))
                continue
            if session.message_type is not MessageType.GROUP_MESSAGE:
                raise wire.ProtocolError("group_mentions_only")
            uid = str(part.qq)
            peer = self.members.get(target, {}).get(uid, "")
            if not peer.isascii() or not peer.isdigit() or not 0 < int(peer) < 1 << 32:
                raise wire.ProtocolError("mention_identity")
            nick = str(part.name or uid)
            start = len(text.encode("utf-16-le")) // 2
            text += f"@{nick} "
            people.append(
                {
                    "uid": int(peer),
                    "nick": nick,
                    "start": start,
                    "end": len(text.encode("utf-16-le")) // 2,
                }
            )
        if not text.strip():
            raise wire.ProtocolError("text_empty")
        key = "proactive/" + (operation_id or uuid.uuid4().hex)
        result = await self.send_reply_text(
            target, key, text, mentions=people or None, proactive=True
        )
        return {"operation_id": key.removeprefix("proactive/"), "status": result}

    async def terminate(self) -> None:
        """Stop event processing and transport before releasing account ownership."""
        self.stopping.set()
        if (
            self.runner
            and self.runner is not asyncio.current_task()
            and not self.runner.done()
        ):
            self.runner.cancel()
            await asyncio.gather(self.runner, return_exceptions=True)
        self.connection_state = "stopped"
        self.status = PlatformStatus.STOPPED
