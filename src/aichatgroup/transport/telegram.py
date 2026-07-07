"""TelegramTransport —— 多 bot 落地面（M1）。

拓扑（摄入与发送分离，见计划 M1）：
- **观察者 bot**：一个开了 *隐私模式关闭* 的 bot，long-polling 摄入群里**人类**发的
  全部消息，push 进 InboundMessage 队列形成唯一共享历史。
  （Telegram 规则：bot 收不到其他 bot 的消息——所以角色 bot 发的话不会被观察者回灌，
  它们由 Orchestrator 直接入历史，天然不重复。）
- **角色 bot**：每个角色一个 bot（各自 token），只负责 `sendChatAction: typing` + 发文本。

依赖 python-telegram-bot（v20+，异步）。懒加载：不装也能跑离线/测试（用 InMemoryTransport）。

⚠️ 必须在 BotFather 里对观察者 bot 关掉 privacy mode（/setprivacy → Disable），
否则它只能收到命令、收不到群里的普通消息。
"""
from __future__ import annotations

import asyncio
import logging

from ..domain.types import Agent
from .base import InboundMessage

logger = logging.getLogger(__name__)


class TelegramTransport:
    def __init__(
        self,
        observer_token: str,
        chat_id: str | int,
        agent_tokens: dict[str, str],
        *,
        command_prefixes: tuple[str, ...] = ("/pause", "/resume", "/status", "/stop"),
    ) -> None:
        self.observer_token = observer_token
        self.chat_id = int(chat_id)
        self.agent_tokens = agent_tokens
        self.command_prefixes = command_prefixes
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()

        # 懒加载 python-telegram-bot，缺失给出清晰指引
        try:
            from telegram import Bot  # noqa: F401
            from telegram.ext import Application, MessageHandler, filters
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "TelegramTransport 需要 python-telegram-bot：\n"
                "  uv add python-telegram-bot   # 或 uv run --with python-telegram-bot ..."
            ) from exc

        self._Bot = Bot
        self._observer_app = Application.builder().token(observer_token).build()
        self._observer_app.add_handler(
            MessageHandler(filters.TEXT & (~filters.StatusUpdate.ALL), self._on_message)
        )
        # 每个角色一个 Bot 客户端（只发不收）
        self._agent_bots = {aid: Bot(token) for aid, token in agent_tokens.items()}

    async def _on_message(self, update, context) -> None:  # telegram 回调签名
        msg = update.effective_message
        if msg is None or msg.chat_id != self.chat_id:
            return
        text = msg.text or ""
        sender = (msg.from_user.full_name if msg.from_user else None) or "匿名"
        external_id = f"{msg.chat_id}:{msg.message_id}"
        is_command = text.strip().split(" ", 1)[0].lower() in self.command_prefixes
        reply = msg.reply_to_message
        reply_ext = f"{msg.chat_id}:{reply.message_id}" if reply is not None else None
        self._inbound.put_nowait(
            InboundMessage(
                speaker=sender, text=text, external_id=external_id,
                is_command=is_command, reply_to_external_id=reply_ext,
            )
        )

    async def start(self) -> None:
        await self._observer_app.initialize()
        await self._observer_app.start()
        await self._observer_app.updater.start_polling(drop_pending_updates=True)
        logger.info("TelegramTransport 已启动，观察群 chat_id=%s", self.chat_id)

    async def stop(self) -> None:
        try:
            await self._observer_app.updater.stop()
            await self._observer_app.stop()
            await self._observer_app.shutdown()
        except Exception as exc:  # pragma: no cover
            logger.warning("TelegramTransport 关闭异常：%s", exc)

    async def next_inbound(self) -> InboundMessage:
        return await self._inbound.get()

    async def send_typing(self, agent: Agent) -> None:
        bot = self._agent_bots.get(agent.id)
        if bot is None:
            return
        try:
            await bot.send_chat_action(chat_id=self.chat_id, action="typing")
        except Exception as exc:  # pragma: no cover
            logger.warning("send_typing(%s) 失败：%s", agent.name, exc)

    async def send_text(
        self, agent: Agent, text: str, reply_to_external_id: str | None = None
    ) -> str | None:
        bot = self._agent_bots.get(agent.id)
        if bot is None:
            logger.warning("角色 %s 无 bot token，无法发送", agent.name)
            return None
        kwargs: dict = {"chat_id": self.chat_id, "text": text}
        if reply_to_external_id:
            try:
                kwargs["reply_to_message_id"] = int(reply_to_external_id.split(":")[-1])
            except ValueError:
                pass
        try:
            sent = await bot.send_message(**kwargs)
            return f"{self.chat_id}:{sent.message_id}"  # 供后续消息回复它
        except Exception as exc:  # pragma: no cover
            logger.warning("send_text(%s) 失败：%s", agent.name, exc)
            return None
