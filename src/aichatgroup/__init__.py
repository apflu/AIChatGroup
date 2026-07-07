"""多模型 AI 群聊引擎 —— transport-agnostic core engine (M0 骨架)。

子包结构:
- domain:   领域数据结构 + 控制标记词表（Agent / WorldBook / RoomState / markers ...）
- gateway:  Model Gateway —— provider 抽象 + AnthropicGateway + MockGateway
- prompt:   分层 Prompt 组装 + 显式 cache_control 断点
- engine:   输出解析（多气泡 + 记忆增量）、气泡节奏、发言回合执行器
- config / logging_setup: 跨层基础设施

常用符号在此层再导出，方便 `from aichatgroup import Agent, run_turn, MockGateway`。
"""
from .domain import (
    Agent,
    ChatMessage,
    PacingConfig,
    RoomState,
    TurnResult,
    Usage,
    WorldBook,
)
from .engine import merge_memory, parse_turn_output, resolve_pauses, run_turn
from .gateway import AnthropicGateway, ModelGateway, MockGateway
from .prompt import build_prompt

__version__ = "0.0.1"

__all__ = [
    "Agent",
    "ChatMessage",
    "PacingConfig",
    "RoomState",
    "TurnResult",
    "Usage",
    "WorldBook",
    "ModelGateway",
    "AnthropicGateway",
    "MockGateway",
    "build_prompt",
    "parse_turn_output",
    "resolve_pauses",
    "run_turn",
    "merge_memory",
    "__version__",
]
