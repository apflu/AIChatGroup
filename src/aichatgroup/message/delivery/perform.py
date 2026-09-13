"""演出：把一个生成回合按气泡投递到 transport（Plan → Generate → **Perform** 的第三段）。

投递按 part kind 分流（两平面：舞台层不由角色第一人称括号发）：
- 举动(beat)   → 旁白（`send_system`）第三人称播报，多数是「先动手、再开口」，故先于台词；
- 神态(gesture)→ 隐去，不投递（仍在历史里）；
- 台词(speech) → 角色出口：typing 提示 → 按节奏等待 → `send_text`（可挂原生 reply）。

回复寻址：`{{REPLY:id}}` 的目标只在**近窗**里找。超窗（已滑出 room.history）刻意不挂原生 reply
——那些平台 message_id 多已失效（尤其跨运行），而被回复内容已由 builder 的超窗内联重注入承载。
近窗内还要过 transport 的平台限制（`can_reply_natively`），不行的同样只靠内联引用 + reply_to_id。

每条气泡发出后立即回调 `on_sent(bubble, external_id)`，让调用方**逐条**入史——这样在等待节奏时
插进来的人类消息在历史里落在正确的位置。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ...domain.types import Agent, RoomState
from ...io.transport.base import Transport
from ...observability import log_event
from ..generator.parsing import ParsedBubble

if TYPE_CHECKING:  # generator.turn 反向 import 本包的 pacing，运行时不在模块顶层互引
    from ..generator.turn import GeneratedTurn

Sleep = Callable[[float], Awaitable[None]]
OnSent = Callable[[ParsedBubble, "str | None"], None]


def resolve_reply_target(
    transport: Transport, agent: Agent, reply_to: int | None, room: RoomState
) -> str | None:
    """被回复消息的 external_id（可挂原生 reply）或 None。近窗 + 平台允许才给。"""
    if reply_to is None:
        return None
    target = next((m for m in reversed(room.history) if m.id == reply_to), None)
    native_ok = target is not None and transport.can_reply_natively(agent, target)
    ext = target.meta.get("external_id") if (target is not None and native_ok) else None
    log_event(
        "reply_resolve", agent=agent.name, reply_to=reply_to,
        external_id=ext, native_reply=native_ok,
        target=(f"{target.speaker}({target.author_kind}): {target.text[:24]}"
                if target is not None else "(不在近窗)"),
    )
    return ext


async def perform_turn(
    transport: Transport,
    turn: GeneratedTurn,
    room: RoomState,
    *,
    sleep: Sleep,
    on_sent: OnSent,
) -> None:
    """逐条演出一个回合。每条发完立刻 `on_sent(bubble, external_id)`（未发/失败时 ext=None）。"""
    agent = turn.agent
    for pb, pause in zip(turn.bubbles, turn.pauses, strict=True):
        # 举动先由旁白公之于众
        for beat in pb.beats:
            await transport.send_system(f"{agent.name}{beat}")
        ext = None
        speech = pb.text
        if speech.strip():                     # 纯举动/神态气泡台词为空 → 不发，但仍入历史
            await transport.send_typing(agent)
            if pause > 0:
                await sleep(pause)
            target_ext = resolve_reply_target(transport, agent, pb.reply_to, room)
            ext = await transport.send_text(agent, speech, reply_to_external_id=target_ext)
        on_sent(pb, ext)
