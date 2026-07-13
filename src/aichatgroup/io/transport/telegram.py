"""TelegramTransport —— 多 bot 落地面（M1）。

拓扑（摄入与发送分离，见计划 M1）：
- **观察者 bot**：一个开了 *隐私模式关闭* 的 bot，long-polling 摄入群里**人类**发的
  全部消息，push 进 InboundMessage 队列形成唯一共享历史。
  （Telegram 规则：bot 收不到其他 bot 的消息——所以角色 bot 发的话不会被观察者回灌，
  它们由 Orchestrator 直接入历史，天然不重复。）
- **角色 bot**：每个角色一个 bot（各自 token），只负责 `sendChatAction: typing` + 发文本。

依赖 python-telegram-bot（v20+，异步）。懒加载：不装也能跑离线/测试（用 InMemoryTransport）。

⚠️ **所有 bot 都要在 BotFather 关掉 privacy mode**（/setprivacy → Disable）：
- 观察者 bot：否则只收命令、收不到群里普通消息（摄入必需）。
- 角色 bot：privacy on 时该 bot 对群里非自己发的消息"不可见"，`reply_to_message_id` 指向人类消息会
  报 "message to be replied not found"。关掉后才能原生 reply 人类消息。
  （bot 之间互 reply 是 telegram 硬限制，关 privacy 也不行——见 orchestrator._speak 的 native_reply 判断。）
"""
from __future__ import annotations

import asyncio
import logging

from ...domain.types import Agent
from .base import BotProfile, InboundMessage

logger = logging.getLogger(__name__)


class TelegramTransport:
    def __init__(
        self,
        observer_token: str,
        chat_id: str | int,
        agent_tokens: dict[str, str],
        *,
        agent_profiles: dict[str, BotProfile] | None = None,
        command_prefixes: tuple[str, ...] = ("/pause", "/resume", "/status", "/stop"),
    ) -> None:
        self.observer_token = observer_token
        self.chat_id = int(chat_id)
        self.agent_tokens = agent_tokens
        self.agent_profiles = agent_profiles or {}   # agent_id → 展示身份（名字/头像），启动时同步
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
        sender_id = str(msg.from_user.id) if msg.from_user else None   # 稳定用户 id → 世界身份锚点
        external_id = f"{msg.chat_id}:{msg.message_id}"
        is_command = text.strip().split(" ", 1)[0].lower() in self.command_prefixes
        reply = msg.reply_to_message
        reply_ext = f"{msg.chat_id}:{reply.message_id}" if reply is not None else None
        self._inbound.put_nowait(
            InboundMessage(
                speaker=sender, text=text, external_id=external_id,
                is_command=is_command, reply_to_external_id=reply_ext,
                sender_id=sender_id, channel="telegram",
            )
        )

    async def start(self) -> None:
        await self._observer_app.initialize()
        await self._observer_app.start()
        await self._observer_app.updater.start_polling(drop_pending_updates=True)
        logger.info("TelegramTransport 已启动，观察群 chat_id=%s", self.chat_id)
        await self._sync_bot_profiles()

    async def _sync_bot_profiles(self) -> None:
        """启动时把每个角色 bot 的平台展示身份对齐到角色名（+ 预留头像）。"""
        for aid, profile in self.agent_profiles.items():
            bot = self._agent_bots.get(aid)
            if bot is None:
                continue
            await self._set_bot_name(bot, profile.name)
            await self.set_bot_avatar(aid, profile.avatar)   # nullable：None 时 no-op

    async def _set_bot_name(self, bot, name: str) -> None:
        """把角色 bot 的 telegram 展示名同步成角色名。
        幂等——仅当前名不同才改，避开 setMyName 的改名频率限制；失败（限流/网络）不拖垮启动。"""
        try:
            current = await bot.get_my_name()
            if current is not None and current.name == name:
                return
            await bot.set_my_name(name=name)
            logger.info("角色 bot 展示名已更新为「%s」", name)
        except Exception as exc:  # pragma: no cover - 网络/改名限流
            logger.warning("设置 bot 展示名「%s」失败（可能触发改名频率限制）：%s", name, exc)

    async def set_bot_avatar(self, agent_id: str, avatar: str | None) -> None:
        """【预留 · nullable】设置角色 bot 头像。avatar 为 None 时不做任何事。

        Telegram Bot API 目前**不支持**编程设置 bot 头像（只能经 BotFather 手动），
        故即便传非 None 也仅记录、不生效；等平台支持或换 transport 时在此接实现。"""
        if avatar is None:
            return
        logger.info(
            "bot 头像设置暂不支持（Telegram Bot API 限制），已忽略 %s 的 avatar=%s",
            agent_id, avatar,
        )

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
            # 回复目标失效（"Message to be replied not found" 等）不该让整条消息消失：
            # 去掉 reply 降级重发一次，宁可丢回复关系也别丢发言。
            if "reply_to_message_id" in kwargs:
                logger.warning("send_text(%s) 带回复失败（%s），降级为普通发送", agent.name, exc)
                kwargs.pop("reply_to_message_id")
                try:
                    sent = await bot.send_message(**kwargs)
                    return f"{self.chat_id}:{sent.message_id}"
                except Exception as exc2:
                    logger.warning("send_text(%s) 降级后仍失败：%s", agent.name, exc2)
                    return None
            logger.warning("send_text(%s) 失败：%s", agent.name, exc)
            return None

    async def send_system(self, text: str) -> None:
        """用 observer bot（bot 0）往群里发一条系统/旁白消息（开发日志转发用）。

        observer bot 收不到自己发的消息 → 不会回灌摄入队列，天然无环。
        """
        try:
            await self._observer_app.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as exc:  # pragma: no cover - 网络失败不回环成 event
            logger.warning("send_system 失败：%s", exc)
