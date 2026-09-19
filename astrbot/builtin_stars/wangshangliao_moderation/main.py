"""Native Wangshangliao moderation commands and automation."""

from sys import maxsize

from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.core import logger
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.filter.command import GreedyStr

from .commands import HELP, PRIVATE_ONLY, Commands
from .policy import handle
from .text import PLAIN_TEXT_INSTRUCTION, plain_text, redact_reply


class Main(star.Star):
    def __init__(self, context):
        self.context = context
        self.commands = Commands()

    @filter.on_llm_request()
    async def plain_text_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """Append platform presentation requirements without replacing the persona."""
        if event.get_platform_name() == "wangshangliao":
            if PLAIN_TEXT_INSTRUCTION not in req.system_prompt:
                req.system_prompt += "\n\n" + PLAIN_TEXT_INSTRUCTION

    @filter.on_decorating_result()
    async def plain_text_result(self, event: AstrMessageEvent):
        """Normalize model text while preserving structured mention components."""
        if event.get_platform_name() != "wangshangliao":
            return
        result = event.get_result()
        if result and result.is_llm_result():
            result.use_t2i(False)
            for component in result.chain:
                if isinstance(component, Plain):
                    component.text = redact_reply(plain_text(component.text))

    @filter.command("群管帮助", alias={"帮助"})
    async def moderation_help(self, event: AstrMessageEvent):
        """List Wangshangliao moderation capabilities and permission requirements."""
        if event.get_platform_name() == "wangshangliao":
            event.set_extra(
                "wsl_command_result", bool(event.get_extra("wsl_test_scope"))
            )
            try:
                await event.send(
                    event.plain_result(
                        redact_reply(HELP if event.is_private_chat() else PRIVATE_ONLY)
                    )
                )
            finally:
                event.stop_event()

    @filter.command("群管")
    async def moderation_command(self, event: AstrMessageEvent, command: GreedyStr):
        """Run a native moderation command without invoking the language model.

        Args:
            event: Authenticated platform event.
            command: Subcommand and arguments.
        """
        if event.get_platform_name() != "wangshangliao":
            return
        from astrbot.core.platform.sources.wangshangliao.wire import ProtocolError

        try:
            response = await self.commands.run(event, command)
        except (ValueError, ProtocolError) as exc:
            logger.warning(
                f"WSL command rejected bot={event.platform.config.get('id', '')} message={event.message_obj.message_id} error={type(exc).__name__}"
            )
            response = "拒绝：参数、身份或授权校验失败。请查看 /群管帮助。"
        except Exception as exc:
            logger.error(
                f"WSL command failed bot={event.platform.config.get('id', '')} message={event.message_obj.message_id} error={type(exc).__name__}"
            )
            response = (
                "处理失败，请检查日志；若已提交管理操作，请先查询结果，不要重复处罚。"
            )
        event.set_extra("wsl_command_result", bool(event.get_extra("wsl_test_scope")))
        try:
            await event.send(event.plain_result(redact_reply(response)))
        finally:
            event.stop_event()

    @filter.event_message_type(
        filter.EventMessageType.ALL, priority=maxsize, context_only=True
    )
    async def moderate(self, event: AstrMessageEvent) -> None:
        """Handle authenticated group events without waking the language model.

        Args:
            event: AstrBot event produced by the native adapter.
        """
        if event.get_platform_name() != "wangshangliao" or event.is_private_chat():
            return
        from astrbot.core.platform.sources.wangshangliao.event import is_managed_account

        payload = event.get_extra("wangshangliao_payload")
        if not payload:
            return
        handlers = event.get_extra("activated_handlers") or []
        params = event.get_extra("handlers_parsed_params") or {}
        if event.is_admin():
            for handler in handlers:
                callback = getattr(handler.handler, "__func__", handler.handler)
                if callback is Main.moderation_command:
                    command = params.get(handler.handler_full_name, {}).get(
                        "command", ""
                    )
                    action = command.strip().split(" ", 1)[0]
                    if action in {
                        "禁言",
                        "解禁",
                        "踢出",
                        "公告",
                        "全员禁言",
                        "解除全员禁言",
                    }:
                        return
        if (
            is_managed_account(event.get_sender_id())
            and event.get_extra("wsl_test_scope") != "group_rules"
        ):
            return
        if await handle(
            event.platform, event.get_group_id(), event.message_obj.message_id, payload
        ):
            event.stop_event()
