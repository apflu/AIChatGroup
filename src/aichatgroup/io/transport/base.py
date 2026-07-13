"""Transport 抽象接口（transport-agnostic 的边界）。

核心引擎不认识 Telegram / Foundry；它只通过 Transport 收发消息。
Telegram、Foundry、以及测试用的 InMemoryTransport 都实现这一个协议。

约定（M1 共享全知）：
- 摄入与发送分离。`next_inbound()` 只吐「外部世界」进来的消息（人类 PL、
  或其他非本引擎控制的来源）。本引擎自己让角色说出来的话不走这里回灌——
  它们由 Orchestrator 直接追加进共享历史，避免重复摄入。
- `send_typing` / `send_text` 以 Agent 为单位发出（每个角色一个「出口」，
  Telegram 里就是每个角色一个 bot）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ...domain.types import Agent


@dataclass
class InboundMessage:
    """从外部世界摄入的一条消息。

    external_id 用于跨重启去重（Telegram 里是 chat_id:message_id）。
    is_command 为 True 表示这是一条控制指令（如 /pause），不进聊天历史。
    """

    speaker: str
    text: str
    external_id: str | None = None
    is_command: bool = False
    # 若这条是「回复某条消息」，被回复消息的 external_id（如 telegram chat:msgid）
    reply_to_external_id: str | None = None
    # 发送者的**稳定**外部 id（如 telegram from_user.id）+ 渠道，用于解析世界身份（PlayerRegistry）。
    # speaker 是显示名（会变），sender_id 才是身份锚点。
    sender_id: str | None = None
    channel: str = ""


@dataclass
class BotProfile:
    """角色 bot 的展示身份，session 启动时由 transport 同步到平台。

    Telegram：`name` → `setMyName`；`avatar` 预留——Bot API 目前不支持编程设置 bot 头像
    （只能 BotFather 手动），故 avatar 是 **nullable 占位**，非 None 时也仅记录、不生效。
    """

    name: str
    avatar: str | None = None   # 头像文件路径 / URL；平台支持后再接（见 TelegramTransport.set_bot_avatar）


@runtime_checkable
class Transport(Protocol):
    """收发消息的薄适配层。实现方负责把外部事件转成 InboundMessage。"""

    async def start(self) -> None:
        """启动底层连接（如 Telegram long polling）。"""
        ...

    async def stop(self) -> None:
        """优雅关闭。"""
        ...

    async def next_inbound(self) -> InboundMessage:
        """阻塞等待并返回下一条摄入消息。"""
        ...

    async def send_typing(self, agent: Agent) -> None:
        """以该角色的身份发出「正在输入」提示（可为 no-op）。"""
        ...

    async def send_text(
        self, agent: Agent, text: str, reply_to_external_id: str | None = None
    ) -> str | None:
        """以该角色的身份发出一条文本气泡；可回复某条消息。

        返回发出消息的 external_id（供后续消息回复它）；发送失败或无从获取时返回 None。
        """
        ...

    async def send_system(self, text: str) -> None:
        """以「系统/旁白」身份往群里发一条非角色消息（可为 no-op）。

        用途：开发期把结构化事件（storyteller 播种 / conductor fire / usher 升级…）
        转发到群里看（见 runtime/log_relay.py）。Telegram 里由 observer bot（bot 0）代发。
        """
        ...
