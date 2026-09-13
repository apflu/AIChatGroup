"""多模型 AI 群聊引擎 —— transport-agnostic core engine。

子包结构（按用途分包，详见 docs/architecture.md）:
- domain:   共享内核 —— 领域数据结构 + 控制标记/指令词表（Agent / WorldBook / RoomState / markers ...）
- prompts:  整段 prompt 文本资产（*.md）
- message:  前台 —— conductor（谁说话）/ generator（生成回合）/ delivery（演出）/ prompt（分层组装）/ usher
- story:    后台 —— storyteller（会话边界播种意图）/ memory（记忆/压缩）/ sim（TODO）
- io:       出站适配 —— gateway（provider 路由）/ transport（InMemory / Telegram）/ persistence（SQLite + repo）
- runtime:  编排层 —— Orchestrator 主循环 + ConversationSession + MasterSwitch + 装配入口
- presets:  房间预设加载（手写世界书 + 角色卡）
- observability / config / logging_setup: 跨层基础设施

常用符号在此层**惰性**再导出：`from aichatgroup import Agent, Orchestrator, Store` 可用，
但 `import aichatgroup.domain` 不会顺带拖起 sqlite / loguru / 各 provider 适配器。
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__version__ = "0.0.1"

# 公开名 → 定义它的子模块。__getattr__ 首次访问时才 import。
_LAZY: dict[str, str] = {
    # domain
    "Agent": "aichatgroup.domain",
    "Message": "aichatgroup.domain",
    "ContentPart": "aichatgroup.domain",
    "ConversationIntent": "aichatgroup.domain",
    "ConversationEnd": "aichatgroup.domain",
    "PacingConfig": "aichatgroup.domain",
    "Player": "aichatgroup.domain",
    "RoomState": "aichatgroup.domain",
    "TurnResult": "aichatgroup.domain",
    "Usage": "aichatgroup.domain",
    "WorldBook": "aichatgroup.domain",
    # gateway
    "ModelGateway": "aichatgroup.io.gateway",
    "AnthropicGateway": "aichatgroup.io.gateway",
    "OpenAIGateway": "aichatgroup.io.gateway",
    "GeminiGateway": "aichatgroup.io.gateway",
    "MockGateway": "aichatgroup.io.gateway",
    "RouterGateway": "aichatgroup.io.gateway",
    "build_gateway": "aichatgroup.io.gateway",
    # prompt / generator / delivery
    "build_prompt": "aichatgroup.message.prompt",
    "parse_turn_output": "aichatgroup.message.generator",
    "run_turn": "aichatgroup.message.generator",
    "generate_turn": "aichatgroup.message.generator",
    "merge_memory": "aichatgroup.message.generator",
    "resolve_pauses": "aichatgroup.message.delivery",
    # story
    "maybe_compact": "aichatgroup.story.memory",
    "CompactionResult": "aichatgroup.story.memory",
    "Storyteller": "aichatgroup.story.storyteller",
    "StubStoryteller": "aichatgroup.story.storyteller",
    "ModelStoryteller": "aichatgroup.story.storyteller",
    # conductor + 会话结束检测 + usher
    "Conductor": "aichatgroup.message.conductor",
    "ModelConductor": "aichatgroup.message.conductor",
    "RoundRobinConductor": "aichatgroup.message.conductor",
    "EndDetector": "aichatgroup.message.conductor",
    "Usher": "aichatgroup.message.usher",
    "UsherDecision": "aichatgroup.message.usher",
    # transport / persistence
    "Transport": "aichatgroup.io.transport",
    "InboundMessage": "aichatgroup.io.transport",
    "InMemoryTransport": "aichatgroup.io.transport",
    "Store": "aichatgroup.io.persistence",
    "RoomRepository": "aichatgroup.io.persistence",
    # runtime / presets / config / observability
    "Orchestrator": "aichatgroup.runtime",
    "ConversationSession": "aichatgroup.runtime",
    "MasterSwitch": "aichatgroup.runtime",
    "PlayerRegistry": "aichatgroup.runtime",
    "build_orchestrator": "aichatgroup.runtime",
    "RoomPreset": "aichatgroup.presets",
    "load_preset": "aichatgroup.presets",
    "Settings": "aichatgroup.config",
    "ProviderSpec": "aichatgroup.config",
    "load_provider_specs": "aichatgroup.config",
    "log_event": "aichatgroup.observability",
}

__all__ = [*_LAZY, "__version__"]


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value          # 缓存：下次直接命中
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # 让类型检查器/IDE 看得见静态符号
    from .config import ProviderSpec, Settings, load_provider_specs  # noqa: F401
    from .domain import (  # noqa: F401
        Agent,
        ContentPart,
        ConversationEnd,
        ConversationIntent,
        Message,
        PacingConfig,
        Player,
        RoomState,
        TurnResult,
        Usage,
        WorldBook,
    )
    from .io.gateway import (  # noqa: F401
        AnthropicGateway,
        GeminiGateway,
        MockGateway,
        ModelGateway,
        OpenAIGateway,
        RouterGateway,
        build_gateway,
    )
    from .io.persistence import RoomRepository, Store  # noqa: F401
    from .io.transport import InboundMessage, InMemoryTransport, Transport  # noqa: F401
    from .message.conductor import Conductor, EndDetector, ModelConductor, RoundRobinConductor  # noqa: F401
    from .message.delivery import resolve_pauses  # noqa: F401
    from .message.generator import generate_turn, merge_memory, parse_turn_output, run_turn  # noqa: F401
    from .message.prompt import build_prompt  # noqa: F401
    from .message.usher import Usher, UsherDecision  # noqa: F401
    from .observability import log_event  # noqa: F401
    from .presets import RoomPreset, load_preset  # noqa: F401
    from .runtime import (  # noqa: F401
        ConversationSession,
        MasterSwitch,
        Orchestrator,
        PlayerRegistry,
        build_orchestrator,
    )
    from .story.memory import CompactionResult, maybe_compact  # noqa: F401
    from .story.storyteller import ModelStoryteller, Storyteller, StubStoryteller  # noqa: F401
