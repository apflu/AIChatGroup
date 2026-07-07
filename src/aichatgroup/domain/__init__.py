"""领域层：数据结构与控制标记词表（无外部/内部依赖，可被各层复用）。"""
from .markers import BUBBLE_SEPARATOR, MEMORY_MARKER
from .types import (
    Agent,
    ChatMessage,
    ContentPart,
    GatewayResponse,
    Message,
    PacingConfig,
    RoomState,
    TurnResult,
    Usage,
    WorldBook,
)

__all__ = [
    "BUBBLE_SEPARATOR",
    "MEMORY_MARKER",
    "Agent",
    "Message",
    "ContentPart",
    "ChatMessage",
    "GatewayResponse",
    "PacingConfig",
    "RoomState",
    "TurnResult",
    "Usage",
    "WorldBook",
]
