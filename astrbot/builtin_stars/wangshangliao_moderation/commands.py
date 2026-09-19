"""Administrator commands using native platform capabilities."""

import hashlib
import sqlite3
import time

from astrbot.core.platform.sources.wangshangliao.storage import instance_dir

HELP = """【旺商聊群管帮助】

【身份与权限】
/sid  获取自己的 UID
/群管 我的权限  查看管理员身份
管理员由 AstrBot 配置，不支持聊天自授权。

【私聊管理 · 管理员】
1. /群管 群列表
2. /群管 选择群 1
3. /群管 成员列表
   /群管 成员搜索 小明
   /群管 下一页
4. /群管 禁言 2
   /群管 解禁 2
   /群管 踢出 2
编号绑定当前列表，十分钟有效。

【群内管理 · 管理员】
@机器人 /群管 禁言 @成员
@机器人 /群管 解禁 @成员
@机器人 /群管 踢出 @成员
@机器人 /群管 公告 公告内容
@机器人 /群管 全员禁言
@机器人 /群管 解除全员禁言
请使用客户端成员选择器进行真实 @。
私聊选群后也可执行公告、全员禁言及解除。

【私聊查询 · 管理员】
/群管 能力
/群管 规则
/群管 违规计数
/群管 结果 <操作ID>
/群管 开发门禁

【说明】
群内只支持上述六项管理动作，不展示查询数据。
动作仍需机器人群授权及平台权限。
撤回仅通过自动违规规则执行。
开发门禁仅在 Dashboard 开启。
已接受不等于已确认；未知结果不要重复提交。"""

PRIVATE_ONLY = "此功能仅限私聊，请私信机器人使用 /群管帮助。"


class Commands:
    """Keep short-lived directory selections isolated by login and caller."""

    def __init__(self):
        self.selections = {}

    async def run(self, event, command: str) -> str:
        """Execute one command with authoritative identity and capability checks.

        Args:
            event: Native authenticated message event.
            command: Subcommand and arguments, excluding the command prefix.

        Returns:
            A bounded text response, with no implied delivery confirmation.
        """
        action, _, argument = command.strip().partition(" ")
        argument = argument.strip()
        actions = {
            "禁言": "mute",
            "解禁": "unmute",
            "踢出": "kick",
            "公告": "announce",
            "全员禁言": "mute_all",
            "解除全员禁言": "unmute_all",
        }
        if not event.is_private_chat():
            if action not in actions:
                return PRIVATE_ONLY
            payload = event.get_extra("wangshangliao_payload") or {}
            if str(event.platform.nim_account) not in payload.get("mentions", []):
                return "请真实 @ 当前机器人后执行群管理命令。"
        if action in {"", "帮助"}:
            return HELP
        if action == "我的权限":
            return f"【我的权限】\nUID: {event.get_sender_id()}\nAstrBot 管理员: {'是' if event.is_admin() else '否'}"
        if not event.is_admin():
            return (
                "拒绝：需要 AstrBot 管理员权限。私聊 /sid 获取 UID 后到 AstrBot 配置。"
            )
        adapter = event.platform
        if action == "开发门禁":
            window = getattr(adapter, "test_window", None)
            state = window.status() if window else {}
            return (
                f"【开发门禁】\n状态：{'开启' if state.get('active') else '关闭'}\n"
                f"剩余时间：{state.get('seconds', 0)} 秒\n"
                f"剩余入站次数：{state.get('remaining', 0)}\n"
                f"发送实例：{state.get('sender_instance', '未设置')}"
            )
        key = (
            id(adapter),
            adapter.account,
            event.get_sender_id(),
            event.unified_msg_origin,
        )
        now = time.monotonic()
        self.selections = {
            k: v for k, v in self.selections.items() if now < v["expires"]
        }
        selection = self.selections.get(key, {})
        group = event.get_group_id() or selection.get("group", "")
        if action == "群列表":
            groups = sorted(adapter.groups)
            self.selections[key] = {"expires": now + 600, "groups": groups}
            return "已启用群（编号十分钟有效）：\n" + "\n".join(
                f"{i}. {g}" for i, g in enumerate(groups, 1)
            )
        if action == "选择群":
            if not event.is_private_chat():
                return "群内自动使用当前群。"
            index = int(argument)
            groups = selection.get("groups", [])
            if not 1 <= index <= len(groups):
                return "编号无效或过期，请重新执行 /群管 群列表。"
            selection.update(group=groups[index - 1], members=[])
            return f"当前群：{selection['group']}"
        if not group or group not in adapter.config.get("enabled_groups", []):
            return "目标群未启用或尚未选择，请先 /群管 群列表。"
        if action == "能力":
            granted = (
                adapter.config.get("moderation", {})
                .get("permissions", {})
                .get(group, [])
            )
            labels = {value: name for name, value in actions.items()}
            labels["recall"] = "违规撤回"
            return (
                f"【当前群动作授权】\n群：{group}\n"
                + (
                    "\n".join(f"- {labels.get(a, a)}" for a in granted)
                    or "未授权任何动作"
                )
                + "\n\n实际执行仍需平台权限。"
            )
        if action == "规则":
            p = adapter.config.get("moderation", {})
            return (
                f"【当前规则】\n群：{group}\n"
                f"群管：{'开启' if p.get('enabled') else '关闭'}\n"
                f"自动规则：{'开启' if p.get('automation_enabled') else '关闭'}\n"
                f"违规撤回：{'开启' if p.get('recall_enabled') else '关闭'}\n"
                f"冷却：{p.get('cooldown_seconds', 0)} 秒\n\n"
                f"禁言关键词：{'、'.join(p.get('mute_keywords') or []) or '未设置'}\n"
                f"踢出关键词：{'、'.join(p.get('kick_keywords') or []) or '未设置'}"
            )[:3000]
        if action in {"成员列表", "成员搜索"}:
            roster = await adapter.get_moderation_members(group)
            members = [
                {
                    **m,
                    "display_name": str(
                        m.get("groupMemberNick")
                        or m.get("userNick")
                        or m.get("nickname")
                        or m.get("name")
                        or m["userId"]
                    ),
                }
                for m in roster["groupMemberInfo"]
            ]
            if action == "成员搜索":
                if not argument:
                    return "用法：/群管 成员搜索 <名称>"
                members = [
                    m
                    for m in members
                    if argument.casefold() in m["display_name"].casefold()
                ]
            selection = {
                "expires": now + 600,
                "group": group,
                "all_members": members,
                "offset": 0,
            }
            self.selections[key] = selection
        if action in {"成员列表", "成员搜索", "下一页"}:
            if "all_members" not in selection:
                return "列表已过期，请重新查询成员。"
            members = selection["all_members"]
            offset = selection["offset"]
            page = []
            lines = []
            size = 0
            for member in members[offset:]:
                name = (
                    member["display_name"]
                    .encode("utf-8")[:240]
                    .decode("utf-8", errors="ignore")
                )
                line = f"{len(page) + 1}. {name} ({member['userId']})"
                length = len(line.encode("utf-8")) + 1
                if page and (size + length > 2800 or len(page) >= 30):
                    break
                page.append(member)
                lines.append(line)
                size += length
            selection.update(members=page, offset=offset + len(page))
            more = selection["offset"] < len(members)
            return (
                "成员快照（当前页编号，十分钟有效）：\n"
                + ("\n".join(lines) or "没有更多成员。")
                + ("\n下一页：/群管 下一页" if more else "\n已到末页。")
            )
        if action == "结果":
            result = await adapter.get_moderation_result(argument, group)
            if not result:
                return "当前群没有此操作。"
            labels = {value: name for name, value in actions.items()}
            labels["recall"] = "违规撤回"
            states = {
                "accepted": "服务端已接受，尚未确认",
                "verified": "已确认",
                "rejected": "拒绝",
                "unknown": "未知，不自动重试",
            }
            return (
                f"【操作结果】\n状态：{states.get(result.get('status'), '未知')}\n"
                f"群：{group}\n动作：{labels.get(result.get('action'), '未知')}\n操作ID：{argument}"
            )
        if action == "违规计数":
            path = instance_dir(adapter.config["id"]) / "moderation.sqlite3"
            if not path.exists():
                return "暂无记录。"
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='violations'"
                ).fetchone():
                    return "暂无记录。"
                rows = db.execute(
                    "SELECT sender,count,started FROM violations WHERE account=? AND group_id=? AND started>? LIMIT 30",
                    (adapter.account, group, time.time() - 86400),
                ).fetchall()
                return "【24小时内违规计数】\n" + (
                    "\n".join(
                        f"- 账号 {sender}：{count} 次" for sender, count, _ in rows
                    )
                    or "暂无记录"
                )
        if action not in actions:
            return HELP
        member = 0
        if action in {"禁言", "解禁", "踢出"}:
            roster = await adapter.get_moderation_members(group)
            if event.is_private_chat():
                index = int(argument)
                members = selection.get("members", [])
                if not 1 <= index <= len(members):
                    return "成员编号无效或过期，请重新查询成员。"
                selected = members[index - 1]
                matches = [
                    m
                    for m in roster["groupMemberInfo"]
                    if str(m["userId"]) == str(selected["userId"])
                    and m.get("nimId") == selected.get("nimId")
                ]
            else:
                payload = event.get_extra("wangshangliao_payload") or {}
                peers = set(payload.get("mentions", [])) - {str(adapter.nim_account)}
                matches = [
                    m for m in roster["groupMemberInfo"] if str(m.get("nimId")) in peers
                ]
                if len(peers) != 1:
                    return "请通过成员选择器真实 @ 一个目标成员。"
            if len(matches) != 1:
                return "拒绝：目标身份映射不明确，请重新选择。"
            member = int(matches[0]["userId"])
        operation = (
            "command/"
            + hashlib.sha256(
                f"{adapter.account}/{event.unified_msg_origin}/{event.message_obj.message_id}".encode()
            ).hexdigest()
        )
        result = await adapter.execute_moderation(
            operation,
            actions[action],
            int(group),
            member,
            argument if action == "公告" else "",
        )
        status = {
            "accepted": "服务端已接受，尚未确认",
            "verified": "已确认",
            "unknown": "未知，不自动重试",
            "rejected": "拒绝",
        }.get(result.get("status"), "未知")
        return f"{status}\n操作ID：{operation}"
