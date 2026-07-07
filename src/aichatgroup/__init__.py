"""多模型 AI 群聊引擎 —— transport-agnostic core engine。

子包结构:
- domain:      领域数据结构 + 控制标记词表（Agent / WorldBook / RoomState / markers ...）
- gateway:     Model Gateway —— provider 抽象 + AnthropicGateway + MockGateway
- prompt:      分层 Prompt 组装 + 显式 cache_control 断点
- engine:      输出解析（多气泡 + 记忆增量）、气泡节奏、发言回合执行、历史压缩
- director:    调度层 —— 决定下一个说话者（RoundRobin / ModelDirector）
- transport:   收发边界 —— InMemory（测试）/ Telegram（M1 落地）
- persistence: SQLite 会话状态存储
- runtime:     编排层 —— Orchestrator 主循环 + MasterSwitch 开关键
- presets:     房间预设加载（手写世界书 + 角色卡）
- config / logging_setup: 跨层基础设施

常用符号在此层再导出，方便 `from aichatgroup import Agent, run_turn, Orchestrator`。
"""
from .config import ProviderSpec, Settings, load_provider_specs
from .director import Director, ModelDirector, RoundRobinDirector
from .domain import (
    Agent,
    ChatMessage,
    PacingConfig,
    RoomState,
    TurnResult,
    Usage,
    WorldBook,
)
from .engine import (
    CompactionResult,
    maybe_compact,
    merge_memory,
    parse_turn_output,
    resolve_pauses,
    run_turn,
)
from .gateway import (
    AnthropicGateway,
    GeminiGateway,
    ModelGateway,
    MockGateway,
    OpenAIGateway,
    RouterGateway,
    build_gateway,
)
from .persistence import Store
from .presets import RoomPreset, load_preset
from .prompt import build_prompt
from .runtime import MasterSwitch, Orchestrator
from .transport import InboundMessage, InMemoryTransport, Transport

__version__ = "0.0.1"

__all__ = [
    # domain
    "Agent",
    "ChatMessage",
    "PacingConfig",
    "RoomState",
    "TurnResult",
    "Usage",
    "WorldBook",
    # gateway
    "ModelGateway",
    "AnthropicGateway",
    "OpenAIGateway",
    "GeminiGateway",
    "MockGateway",
    "RouterGateway",
    "build_gateway",
    # prompt / engine
    "build_prompt",
    "parse_turn_output",
    "resolve_pauses",
    "run_turn",
    "merge_memory",
    "maybe_compact",
    "CompactionResult",
    # director
    "Director",
    "ModelDirector",
    "RoundRobinDirector",
    # transport
    "Transport",
    "InboundMessage",
    "InMemoryTransport",
    # persistence / runtime / presets / config
    "Store",
    "Orchestrator",
    "MasterSwitch",
    "RoomPreset",
    "load_preset",
    "Settings",
    "ProviderSpec",
    "load_provider_specs",
    # meta
    "__version__",
]
