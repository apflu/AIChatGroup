"""多模型 AI 群聊引擎 —— transport-agnostic core engine。

子包结构（按用途分包，详见 docs/architecture.md）:
- domain:   共享内核 —— 领域数据结构 + 控制标记词表（Agent / WorldBook / RoomState / markers ...）
- message:  前台平面 —— conductor（谁说话）/ generator（生成回合）/ delivery（节奏）/ prompt（分层组装）
- story:    后台暗线 —— memory（记忆/压缩），storyteller / sim（TODO）
- io:       出站适配 —— gateway（provider 路由）/ transport（InMemory / Telegram）/ persistence（SQLite）
- runtime:  编排层 —— Orchestrator 主循环 + MasterSwitch 开关键 + telegram_app 装配
- presets:  房间预设加载（手写世界书 + 角色卡）
- observability / config / logging_setup: 跨层基础设施

常用符号在此层再导出，方便 `from aichatgroup import Agent, run_turn, Orchestrator`。
"""
from .config import ProviderSpec, Settings, load_provider_specs
from .message.conductor import Director, ModelDirector, RoundRobinDirector
from .domain import (
    Agent,
    ChatMessage,
    ContentPart,
    Message,
    PacingConfig,
    RoomState,
    TurnResult,
    Usage,
    WorldBook,
)
from .message.generator import merge_memory, parse_turn_output, run_turn
from .message.delivery import resolve_pauses
from .story.memory import CompactionResult, maybe_compact
from .observability import log_event
from .io.gateway import (
    AnthropicGateway,
    GeminiGateway,
    ModelGateway,
    MockGateway,
    OpenAIGateway,
    RouterGateway,
    build_gateway,
)
from .io.persistence import Store
from .presets import RoomPreset, load_preset
from .message.prompt import build_prompt
from .runtime import MasterSwitch, Orchestrator
from .io.transport import InboundMessage, InMemoryTransport, Transport

__version__ = "0.0.1"

__all__ = [
    # domain
    "Agent",
    "Message",
    "ContentPart",
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
    "log_event",
    # meta
    "__version__",
]
