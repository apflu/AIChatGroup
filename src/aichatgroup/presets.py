"""房间预设加载 —— 手写世界书 + 角色卡的落地形式（M1）。

一个 JSON 文件描述一个群聊房间：世界书、房间种子（长期摘要/客观关系）、
以及一组角色（含 RisuAI 式层级：base_prompt → character_card、每角色 model_id
与 PacingConfig）。Telegram 相关（每角色 bot token、观察者 token、群 chat_id）
以 *_env 形式给出环境变量名，加载时从 os.environ 解析，token 不落进版本库。

世界书/角色卡是**文件**而非数据库（见计划数据模型注）；SQLite 只存可变会话状态。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import ProviderSpec
from .domain.types import Agent, PacingConfig, WorldBook


@dataclass
class AgentTelegram:
    agent_id: str
    bot_token: str | None  # 从 *_env 解析；缺失为 None（离线时允许）


@dataclass
class TelegramConfig:
    observer_token: str | None = None
    chat_id: str | None = None
    agents: dict[str, AgentTelegram] = field(default_factory=dict)


@dataclass
class RoomPreset:
    room_key: str
    world: WorldBook
    agents: list[Agent]
    seed_summary: str = ""
    seed_relations: str = ""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    # 预设可自带 provider 定义（声明式；与全局 providers.json / env 合并）
    providers: list[ProviderSpec] = field(default_factory=list)


def _resolve_env(name: str | None) -> str | None:
    return os.environ.get(name) if name else None


def _build_pacing(raw: dict | None) -> PacingConfig:
    if not raw:
        return PacingConfig()
    fields = {
        "base_pause_s", "per_char_s", "min_pause_s", "max_pause_s", "explicit_scale",
    }
    return PacingConfig(**{k: v for k, v in raw.items() if k in fields})


def load_preset(path: str | os.PathLike[str]) -> RoomPreset:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    world = WorldBook(
        bible=data["world"]["bible"],
        rules=data["world"].get("rules", ""),
    )
    room_seed = data.get("room", {})

    agents: list[Agent] = []
    tg_agents: dict[str, AgentTelegram] = {}
    for a in data["agents"]:
        agents.append(
            Agent(
                id=a["id"],
                name=a["name"],
                model_id=a["model_id"],
                base_prompt=a.get("base_prompt", ""),
                character_card=a.get("character_card", ""),
                pacing=_build_pacing(a.get("pacing")),
            )
        )
        tg_agents[a["id"]] = AgentTelegram(
            agent_id=a["id"],
            bot_token=_resolve_env(a.get("bot_token_env")),
        )

    tg_raw = data.get("telegram", {})
    telegram = TelegramConfig(
        observer_token=_resolve_env(tg_raw.get("observer_token_env")),
        chat_id=_resolve_env(tg_raw.get("chat_id_env")) or tg_raw.get("chat_id"),
        agents=tg_agents,
    )

    providers = [ProviderSpec.from_dict(x) for x in data.get("providers", [])]

    return RoomPreset(
        room_key=data.get("room_key", "default"),
        world=world,
        agents=agents,
        seed_summary=room_seed.get("long_term_summary", ""),
        seed_relations=room_seed.get("objective_relations", ""),
        telegram=telegram,
        providers=providers,
    )
