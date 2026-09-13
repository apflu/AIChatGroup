"""单角色发言回合的生成：组装分层 prompt → 调用其绑定模型 → 解析气泡 + 记忆增量 + 节奏。

**唯一一份真相**：Orchestrator（在线）与 replay/测试（离线 `run_turn`）都走同一条
prepare → complete → finish 路径，不再各抄一份解析/节奏逻辑。

- `prepare_turn`：只读 room，产出 (system, messages)。
- `finish_turn`：拿模型响应，解析成 `GeneratedTurn`（气泡草稿 + 每条停顿 + 记忆增量 + 用量）。
- 两步之间的网络调用由调用方决定怎么跑（Orchestrator 下放线程池，离线直接同步）。
- `generate_turn` = 三步连起来（同步）；`run_turn` 再把结果**就地应用**到 room（离线/回放用）。

停顿按**台词**长度算（动作已剥离、不由角色 bot 打字）；纯举动气泡台词为空、停顿退到基础值。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from ...domain.types import Agent, GatewayResponse, RoomState, TurnResult, Usage, WorldBook
from ...io.gateway import ModelGateway
from ...observability import log_event, log_model_raw
from ..delivery.pacing import resolve_pauses
from ..prompt import build_prompt
from .parsing import ParsedBubble, parse_turn_output

logger = logging.getLogger(__name__)


@dataclass
class GeneratedTurn:
    """一个发言回合的生成结果（尚未入史、未投递）。"""

    agent: Agent
    bubbles: list[ParsedBubble]
    pauses: list[float]              # 每条气泡发送前应等待的秒数；pauses[0] 恒 0.0
    memory_delta: dict | None
    usage: Usage
    raw_text: str


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


def prepare_turn(
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    conductor_instruction: str = "",
    resolve: Callable[[int], object] | None = None,
) -> tuple[list[dict], list[dict]]:
    """组装该角色本回合的 (system, messages)。只读 room。"""
    return build_prompt(world, room, agent, conductor_instruction, resolve=resolve)


def finish_turn(agent: Agent, resp: GatewayResponse) -> GeneratedTurn:
    """把模型响应解析成气泡草稿 + 节奏 + 记忆增量；记 FIREHOSE 原文与 TRACE 级用量。"""
    log_model_raw("generator", resp.text, agent=agent.name)
    parsed, memory_delta = parse_turn_output(resp.text, speaker=agent.name)
    pauses = resolve_pauses(
        [pb.text for pb in parsed], [pb.pause_hint for pb in parsed], agent.pacing
    )
    logger.info(
        "回合 %s model=%s bubbles=%d cache_read=%d cache_creation=%d",
        agent.name, agent.model_id, len(parsed),
        resp.usage.cache_read_input_tokens, resp.usage.cache_creation_input_tokens,
    )
    # model_call 只留 output + cache 计数（不记 input tokens），TRACE 级保持可读、够诊断 cache
    log_event(
        "model_call", agent=agent.name, model=agent.model_id, bubbles=len(parsed),
        output_tokens=resp.usage.output_tokens,
        cache_read=resp.usage.cache_read_input_tokens,
        cache_creation=resp.usage.cache_creation_input_tokens,
    )
    return GeneratedTurn(
        agent=agent, bubbles=parsed, pauses=pauses,
        memory_delta=memory_delta, usage=resp.usage, raw_text=resp.text,
    )


def generate_turn(
    gateway: ModelGateway,
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    conductor_instruction: str = "",
    max_tokens: int = 1024,
    resolve: Callable[[int], object] | None = None,
) -> GeneratedTurn:
    """同步三步连跑：prepare → complete → finish。不改 room。"""
    system, messages = prepare_turn(world, room, agent, conductor_instruction, resolve)
    resp = gateway.complete(system, messages, agent.model_id, max_tokens=max_tokens)
    return finish_turn(agent, resp)


def apply_turn(room: RoomState, turn: GeneratedTurn) -> None:
    """离线应用：气泡入共享历史、记忆增量合并进私有快照（在线路径由 Orchestrator 经 repo 写）。"""
    for pb in turn.bubbles:
        room.append(turn.agent.name, parts=pb.parts, reply_to=pb.reply_to)
    if turn.memory_delta:
        room.memory[turn.agent.id] = merge_memory(
            room.memory.get(turn.agent.id, ""), turn.memory_delta
        )


def run_turn(
    gateway: ModelGateway,
    world: WorldBook,
    room: RoomState,
    agent: Agent,
    conductor_instruction: str = "",
    max_tokens: int = 1024,
    apply: bool = True,
) -> TurnResult:
    """离线执行一个发言回合（回放 / 测试）。

    apply=True（默认）会就地更新 room：气泡入历史、记忆增量入私有快照。
    apply=False 只返回结果、不改动 room（便于预演）。
    """
    turn = generate_turn(gateway, world, room, agent, conductor_instruction, max_tokens)
    if apply:
        apply_turn(room, turn)
    return TurnResult(
        agent_id=agent.id,
        bubbles=[pb.display for pb in turn.bubbles],
        memory_delta=turn.memory_delta,
        usage=turn.usage,
        raw_text=turn.raw_text,
        pauses=turn.pauses,
    )
