"""分层 Prompt 组装 + 显式 cache_control 断点（M0 共享全知布局）。

布局（规格 line 65：不做隔离时共享块前置，让所有 Agent 命中同一缓存条目）：

  system:
    [第0层 世界观圣经 + 群聊规则]        ← cache breakpoint 1
    [第1层 长期摘要 + 客观关系图谱]      ← cache breakpoint 2
  messages:
    [第2层 共享历史，逐条 user 消息，append-only]
        └─ 最后一条历史消息           ← 滚动 cache breakpoint 3
    [第3层尾部 该角色人设 + 独知 + 私有记忆 + conductor 指令（会话意图）+ 输出契约]  ← 不缓存

历史全部用 user 角色（带 `[发言者]` 前缀），使得 system+history 前缀对所有 Agent
逐字节相同 → 共享同一缓存车道；模型据此生成 assistant 回合即当前角色的气泡。

ROADMAP —— 向 SillyTavern 预设结构靠拢：
    当前是硬编码的四层组装，本质是 SillyTavern「命名 prompt 片段 + 顺序/开关 +
    marker 占位 + 深度注入」模型的一个特例（见 preset/example.json 的
    prompts / prompt_order）。后续应把各层抽象成可命名、可排序、可开关的片段，
    支持导入 SillyTavern 预设来控制模型行为——但预设不替代本 Builder，只提供结构与文案。
    改造时留意：cache_control 断点要挂在稳定前缀片段的边界上。
"""
from __future__ import annotations

from collections.abc import Callable

from ...domain.types import Agent, RoomState, WorldBook, render_parts
from ...prompts import render as render_prompt

# 返回给 Gateway 的结构：system 为 block 列表，messages 为 {role, content} 列表。
SystemBlock = dict
Message = dict

def _cache(text: str) -> SystemBlock:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


# ---- 各层散文渲染（domain 只存数据；"数据 → 给模型看的文本"在 prompts/role/*.md）-------------

def render_world(world: WorldBook) -> str:
    """第 0 层：世界观圣经 + 群聊规则。"""
    return render_prompt("role/world", bible=world.bible.strip(), rules=world.rules.strip())


def render_layer1(room: RoomState) -> str:
    """第 1 层：前情提要 + 客观关系图谱 + 在场玩家；全空时模板给占位（块非空、断点稳定）。"""
    return render_prompt(
        "role/situation",
        summary=room.long_term_summary.strip(),
        relations=room.objective_relations.strip(),
        players={n: p.strip() for n, p in room.players.items()},
    )


def build_tail(
    agent: Agent,
    memory_text: str,
    conductor_instruction: str,
    granted_knowledge: str = "",
) -> str:
    """第 3 层尾部：人设 + 角色独知世界秘密 + 私有记忆快照 + conductor 指令 + 输出契约（prompts/role/tail.md）。

    per-agent 的知识隔离落在这——尾部本就每 agent 不同且不缓存，注入零缓存回归。独知内情两来源：
    `agent.secret_knowledge`（预设静态）+ `granted_knowledge`（storyteller 边界私授、累积），合并渲染。
    MockGateway 靠 tail.md 里「扮演的角色是「X」」的措辞认出当前角色（见 io/gateway/mock.py）。
    """
    knowledge = "\n".join(
        k for k in (agent.secret_knowledge.strip(), granted_knowledge.strip()) if k
    )
    return render_prompt(
        "role/tail",
        base_prompt=agent.base_prompt.strip(),
        name=agent.name,
        character_card=agent.character_card.strip(),
        knowledge=knowledge,
        memory=memory_text.strip(),
        conductor=conductor_instruction.strip(),
    )


_QUOTE_LEN = 12  # 被回复消息内联引用的定长截断


def _reply_note(reply_to, window_map: dict, resolve) -> str:
    """一条消息回复 ⟦reply_to⟧ 时，渲染进历史的定长引用。

    目标在近窗→直接引；已滑出→用 resolve 从 store 取回（"超窗内联重注入"）。截断定长 →
    对同一目标恒定 → 保共享缓存前缀确定性。目标彻底找不到（如已被 compaction 删）→ 仅标 ⟦id⟧。
    """
    if reply_to is None:
        return ""
    target = window_map.get(reply_to)
    if target is None and resolve is not None:
        target = resolve(reply_to)
    if target is None:
        return f"（回⟦{reply_to}⟧）"
    if getattr(target, "redacted", False):
        # 目标已被清洗：只保留回复指向，绝不漏其内容片段（否则隐藏内容会从幸存回复里回流上下文）
        return f"（回⟦{reply_to}⟧）"
    snippet = (target.text or render_parts(target.parts)).strip()[:_QUOTE_LEN]
    return f"（回⟦{reply_to}⟧「{snippet}…」）" if snippet else f"（回⟦{reply_to}⟧）"


def build_prompt(
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    conductor_instruction: str = "",
    resolve: Callable[[int], object] | None = None,
) -> tuple[list[SystemBlock], list[Message]]:
    """组装一次调用的 (system_blocks, messages)。

    conductor_instruction 是会话意图注入尾部的 hook（不缓存层，保共享前缀不变式）。
    resolve(id)->Message|None 用于把「超出近窗的被回复消息」取回内联引用（通常由 store 提供）。
    """
    system: list[SystemBlock] = [
        _cache(render_world(world)),     # breakpoint 1
        _cache(render_layer1(room)),     # breakpoint 2
    ]

    # 可见性过滤（清洗 + M3 知识隔离的唯一接缝）：只组装对本 agent 可见的历史。
    # redacted 对谁都不可见 → 各 agent 的可见历史仍逐字节一致（只是变短），共享同一缓存车道；
    # visible_to（M3 一般情形）才会 per-agent 分叉车道，默认 None 时此行为完全惰性。
    window_map = {m.id: m for m in room.history}
    visible = room.visible_history(agent.id)
    messages: list[Message] = []
    last = len(visible) - 1
    for i, msg in enumerate(visible):
        note = _reply_note(msg.reply_to, window_map, resolve)
        rendered = msg.render(reply_note=note)
        if i == last:
            # 滚动 breakpoint 3：cache_control 挂在最后一条**可见**历史消息上
            messages.append({"role": "user", "content": [_cache(rendered)]})
        else:
            messages.append({"role": "user", "content": rendered})

    tail = build_tail(
        agent, room.memory.get(agent.id, ""), conductor_instruction,
        granted_knowledge=room.knowledge.get(agent.id, ""),
    )
    messages.append({"role": "user", "content": tail})  # 尾部，不缓存
    return system, messages
