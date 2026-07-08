"""单角色发言回合执行器。

一次调用 = 一个角色的一个发言回合：组装分层 prompt → 调用其绑定模型 →
解析 1~3 条气泡 + 记忆增量 → 把气泡追加进共享历史、把记忆增量合并进私有快照。
"""
from __future__ import annotations

import json
import logging

from ...domain.types import Agent, RoomState, TurnResult, WorldBook
from ...io.gateway import ModelGateway
from ..prompt import build_prompt
from ..delivery.pacing import resolve_pauses
from .parsing import parse_turn_output

logger = logging.getLogger(__name__)


def merge_memory(current: str, delta: dict) -> str:
    """把记忆增量合并进私有快照。

    每条 delta 序列化成一行 JSON。M2 增强：**追加时去重**——若这行内容已在快照里（逐字节相同），
    不重复堆叠（M1 的裸追加会让反复出现的同一事实无限膨胀）。空快照直接返回该行。
    单条增量、无重复时输出与 M1 逐字节一致，保持既有格式契约。
    """
    line = json.dumps(delta, ensure_ascii=False, sort_keys=True)
    if not current.strip():
        return line
    existing = current.rstrip().split("\n")
    if line in existing:                       # 已记过同一事实 → 不重复堆叠
        return current.rstrip()
    return f"{current.rstrip()}\n{line}".strip()


def run_turn(
    gateway: ModelGateway,
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    conductor_instruction: str = "",
    max_tokens: int = 1024,
    apply: bool = True,
) -> TurnResult:
    """执行一个发言回合。

    conductor_instruction 是会话意图注入尾部的 hook。
    apply=True（默认）会就地更新 room：气泡入历史、记忆增量入私有快照。
    apply=False 只返回结果、不改动 room（便于测试/预演）。
    """
    system, messages = build_prompt(world, room, agent, conductor_instruction)
    resp = gateway.complete(system, messages, agent.model_id, max_tokens=max_tokens)
    parsed, memory_delta = parse_turn_output(resp.text, speaker=agent.name)
    pauses = resolve_pauses(
        [pb.display for pb in parsed], [pb.pause_hint for pb in parsed], agent.pacing
    )

    logger.info(
        "回合 agent=%s model=%s bubbles=%d pauses=%s | input=%d output=%d "
        "cache_read=%d cache_creation=%d",
        agent.name,
        agent.model_id,
        len(parsed),
        [round(p, 2) for p in pauses],
        resp.usage.input_tokens,
        resp.usage.output_tokens,
        resp.usage.cache_read_input_tokens,
        resp.usage.cache_creation_input_tokens,
    )

    if apply:
        for pb in parsed:
            room.append(agent.name, parts=pb.parts, reply_to=pb.reply_to)
        if memory_delta:
            room.memory[agent.id] = merge_memory(room.memory.get(agent.id, ""), memory_delta)

    return TurnResult(
        agent_id=agent.id,
        bubbles=[pb.display for pb in parsed],
        memory_delta=memory_delta,
        usage=resp.usage,
        raw_text=resp.text,
        pauses=pauses,
    )
