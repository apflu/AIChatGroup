"""房间预设加载 —— 手写世界书 + 角色卡的落地形式（M1）。

一个 JSON 文件描述一个群聊房间：世界书、房间种子（长期摘要/客观关系）、
以及一组角色（含 RisuAI 式层级：base_prompt → character_card、每角色 model_id
与 PacingConfig）。

**预设格式是 transport 无关的**：平台相关的段落原样保留为 `transports[<name>]`（如
`transports.telegram` / 旧式顶层 `telegram`），角色卡里引擎不认识的键原样保留为
`agent_options[agent_id]`（如 `bot_token_env`）。各 transport 自己从这两处读它要的东西
（见 io/transport/telegram.py::TelegramConfig.from_preset）。凡以 `_env` 结尾的键，加载时从
os.environ 解析成同名（去后缀）的值——token 不落进版本库。

世界书/角色卡是**文件**而非数据库（见计划数据模型注）；SQLite 只存可变会话状态。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import ProviderSpec
from .domain.types import Agent, PacingConfig, WorldBook

# 角色卡里引擎自己消费的键；其余原样进 agent_options（各 transport 自取）
_AGENT_CORE_KEYS = frozenset({
    "id", "name", "model_id", "base_prompt", "character_card", "secret_knowledge", "pacing",
})
_PACING_KEYS = frozenset({
    "base_pause_s", "per_char_s", "min_pause_s", "max_pause_s", "explicit_scale",
})


@dataclass
class PresetPlayer:
    """预设预登记的玩家：把稳定外部 id（直填或 *_env 指向环境变量）绑到世界名+人设。"""

    name: str
    persona: str = ""
    channel: str = ""
    external_id: str = ""          # 缺失（未配 id）则加载时留空，seed 时跳过


@dataclass
class RoomPreset:
    room_key: str
    world: WorldBook
    agents: list[Agent]
    seed_summary: str = ""
    seed_relations: str = ""
    players: list[PresetPlayer] = field(default_factory=list)
    # 预设可自带 provider 定义（声明式；与全局 providers.json / env 合并）
    providers: list[ProviderSpec] = field(default_factory=list)
    # 平台段落（原样 + *_env 已解析）：transports["telegram"] = {"observer_token": ..., "chat_id": ...}
    transports: dict[str, dict] = field(default_factory=dict)
    # 角色卡里引擎不认识的键（原样 + *_env 已解析）：agent_options["a1"] = {"bot_token": ...}
    agent_options: dict[str, dict] = field(default_factory=dict)


def resolve_env_keys(raw: dict) -> dict:
    """把 `{"x_env": "VAR"}` 解析成 `{"x": os.environ["VAR"]}`（未设则 None）；其余键原样。
    显式给的 `x` 优先于 `x_env`。"""
    out: dict = {}
    for k, v in raw.items():
        if k.endswith("_env"):
            base = k[: -len("_env")]
            if base not in raw:
                out[base] = os.environ.get(v) if v else None
        else:
            out[k] = v
    return out


def _build_pacing(raw: dict | None) -> PacingConfig:
    if not raw:
        return PacingConfig()
    return PacingConfig(**{k: v for k, v in raw.items() if k in _PACING_KEYS})


def _load_player(pl: dict) -> PresetPlayer:
    # 旧式 telegram_id / telegram_id_env 隐含 channel=telegram；新式 external_id(_env) + channel
    if "telegram_id" in pl or "telegram_id_env" in pl:
        ext = os.environ.get(pl["telegram_id_env"]) if pl.get("telegram_id_env") else None
        ext = ext or str(pl.get("telegram_id", "") or "")
        channel = pl.get("channel", "telegram")
    else:
        ext = os.environ.get(pl["external_id_env"]) if pl.get("external_id_env") else None
        ext = ext or str(pl.get("external_id", "") or "")
        channel = pl.get("channel", "")
    return PresetPlayer(name=pl["name"], persona=pl.get("persona", ""), channel=channel, external_id=ext)


def load_preset(path: str | os.PathLike[str]) -> RoomPreset:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    world = WorldBook(
        bible=data["world"]["bible"],
        rules=data["world"].get("rules", ""),
    )
    room_seed = data.get("room", {})

    agents: list[Agent] = []
    agent_options: dict[str, dict] = {}
    for a in data["agents"]:
        agents.append(
            Agent(
                id=a["id"],
                name=a["name"],
                model_id=a["model_id"],
                base_prompt=a.get("base_prompt", ""),
                character_card=a.get("character_card", ""),
                secret_knowledge=a.get("secret_knowledge", ""),
                pacing=_build_pacing(a.get("pacing")),
            )
        )
        extras = {k: v for k, v in a.items() if k not in _AGENT_CORE_KEYS}
        agent_options[a["id"]] = resolve_env_keys(extras)

    transports = {
        name: resolve_env_keys(section or {})
        for name, section in (data.get("transports") or {}).items()
    }
    if "telegram" in data and "telegram" not in transports:     # 旧式顶层 telegram 块
        transports["telegram"] = resolve_env_keys(data["telegram"] or {})

    providers = [ProviderSpec.from_dict(x) for x in data.get("providers", [])]
    players = [_load_player(pl) for pl in data.get("players", [])]

    return RoomPreset(
        room_key=data.get("room_key", "default"),
        world=world,
        agents=agents,
        seed_summary=room_seed.get("long_term_summary", ""),
        seed_relations=room_seed.get("objective_relations", ""),
        players=players,
        providers=providers,
        transports=transports,
        agent_options=agent_options,
    )
