"""领域层：数据结构与控制标记词表（无外部/内部依赖，可被各层复用）。"""
from .conversation import (
    CHITCHAT,
    DEADLOCK,
    DEVELOP_PLOT,
    END_REASONS,
    INTENT_FULFILLED,
    INTENT_KINDS,
    LULL,
    MAX_LENGTH,
    RESOLVE_TENSION,
    USER_FORCED,
    ConversationEnd,
    ConversationIntent,
)
from .markers import BUBBLE_SEPARATOR, MEMORY_MARKER, USER_TAG
from .player import STRANGER_NAME, Player, sanitize_player_name
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
    "USER_TAG",
    # player（人类参与者身份）
    "Player",
    "STRANGER_NAME",
    "sanitize_player_name",
    # conversation（会话层契约）
    "ConversationIntent",
    "ConversationEnd",
    "CHITCHAT",
    "DEVELOP_PLOT",
    "RESOLVE_TENSION",
    "INTENT_KINDS",
    "LULL",
    "DEADLOCK",
    "INTENT_FULFILLED",
    "USER_FORCED",
    "MAX_LENGTH",
    "END_REASONS",
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
