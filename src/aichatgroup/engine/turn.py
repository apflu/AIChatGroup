"""单角色发言回合执行器。

一次调用 = 一个角色的一个发言回合：组装分层 prompt → 调用其绑定模型 →
解析 1~3 条气泡 + 记忆增量 → 把气泡追加进共享历史、把记忆增量合并进私有快照。
"""
from __future__ import annotations

import json
import logging

from ..domain.types import Agent, RoomState, TurnResult, WorldBook
from ..gateway import ModelGateway
from ..prompt import build_prompt
from .pacing import resolve_pauses
from .parsing import parse_turn_output

logger = logging.getLogger(__name__)


def merge_memory(current: str, delta: dict) -> str:
    """把记忆增量合并进私有快照。

    M0 策略极简：把 delta 序列化成一行 JSON 追加到快照文本尾部。
    （后续里程碑可换成结构化合并/去重/压缩。）
    """
    line = json.dumps(delta, ensure_ascii=False, sort_keys=True)
    return f"{current.rstrip()}\n{line}".strip() if current.strip() else line


def run_turn(
    gateway: ModelGateway,
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    director_instruction: str = "",
    max_tokens: int = 1024,
    apply: bool = True,
) -> TurnResult:
    """执行一个发言回合。

    apply=True（默认）会就地更新 room：气泡入历史、记忆增量入私有快照。
    apply=False 只返回结果、不改动 room（便于测试/预演）。
    """
    system, messages = build_prompt(world, room, agent, director_instruction)
    resp = gateway.complete(system, messages, agent.model_id, max_tokens=max_tokens)
    bubbles, pause_hints, memory_delta = parse_turn_output(resp.text)
    pauses = resolve_pauses(bubbles, pause_hints, agent.pacing)

    logger.info(
        "回合 agent=%s model=%s bubbles=%d pauses=%s | input=%d output=%d "
        "cache_read=%d cache_creation=%d",
        agent.name,
        agent.model_id,
        len(bubbles),
        [round(p, 2) for p in pauses],
        resp.usage.input_tokens,
        resp.usage.output_tokens,
        resp.usage.cache_read_input_tokens,
        resp.usage.cache_creation_input_tokens,
    )

    if apply:
        for bubble in bubbles:
            room.append(agent.name, bubble)
        if memory_delta:
            room.memory[agent.id] = merge_memory(room.memory.get(agent.id, ""), memory_delta)

    return TurnResult(
        agent_id=agent.id,
        bubbles=bubbles,
        memory_delta=memory_delta,
        usage=resp.usage,
        raw_text=resp.text,
        pauses=pauses,
    )
