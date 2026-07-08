"""分层 Prompt 组装 + 显式 cache_control 断点（M0 共享全知布局）。

布局（规格 line 65：不做隔离时共享块前置，让所有 Agent 命中同一缓存条目）：

  system:
    [第0层 世界观圣经 + 群聊规则]        ← cache breakpoint 1
    [第1层 长期摘要 + 客观关系图谱]      ← cache breakpoint 2
  messages:
    [第2层 共享历史，逐条 user 消息，append-only]
        └─ 最后一条历史消息           ← 滚动 cache breakpoint 3
    [第3层尾部 该角色人设 + 私有记忆 + director 指令 + 输出契约]  ← 不缓存

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

from ...domain.types import Agent, RoomState, WorldBook, render_parts
from ...prompts import load as load_prompt, render as render_prompt

# 返回给 Gateway 的结构：system 为 block 列表，messages 为 {role, content} 列表。
SystemBlock = dict
Message = dict

# 尾部散文都在 prompts/*.md（tail_header / tail_memory / tail_director / output_contract）；
# marker 字面写在 output_contract.md 里，免去 f-string 的 `{{{{}}}}` 转义。
# test_prompts 断言 BUBBLE_SEPARATOR / MEMORY_MARKER 的实际值出现在文本里，防与 markers.py 漂移。
_OUTPUT_CONTRACT = load_prompt("output_contract")


def _cache(text: str) -> SystemBlock:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def build_tail(agent: Agent, memory_text: str, director_instruction: str) -> str:
    """第 3 层尾部：人设 + 私有记忆快照 + director 指令 + 输出契约。"""
    parts = [load_prompt("tail_header"), agent.render_persona()]
    if memory_text.strip():
        parts.append(render_prompt("tail_memory", memory=memory_text.strip()))
    if director_instruction.strip():
        parts.append(render_prompt("tail_director", director=director_instruction.strip()))
    parts.append(_OUTPUT_CONTRACT)
    return "\n\n".join(parts)


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
    snippet = (target.text or render_parts(target.parts)).strip()[:_QUOTE_LEN]
    return f"（回⟦{reply_to}⟧「{snippet}…」）" if snippet else f"（回⟦{reply_to}⟧）"


def build_prompt(
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    director_instruction: str = "",
    resolve: "Callable[[int], object] | None" = None,
) -> tuple[list[SystemBlock], list[Message]]:
    """组装一次调用的 (system_blocks, messages)。

    resolve(id)->Message|None 用于把「超出近窗的被回复消息」取回内联引用（通常由 store 提供）。
    """
    system: list[SystemBlock] = [
        _cache(world.render()),          # breakpoint 1
        _cache(room.render_layer1()),    # breakpoint 2
    ]

    window_map = {m.id: m for m in room.history}
    messages: list[Message] = []
    last = len(room.history) - 1
    for i, msg in enumerate(room.history):
        note = _reply_note(msg.reply_to, window_map, resolve)
        rendered = msg.render(reply_note=note)
        if i == last:
            # 滚动 breakpoint 3：cache_control 挂在最后一条历史消息上
            messages.append({"role": "user", "content": [_cache(rendered)]})
        else:
            messages.append({"role": "user", "content": rendered})

    tail = build_tail(agent, room.memory.get(agent.id, ""), director_instruction)
    messages.append({"role": "user", "content": tail})  # 尾部，不缓存
    return system, messages
