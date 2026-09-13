"""运行时编排层：主循环 + 会话状态机 + 开关键 + 玩家身份 + 装配入口。"""
from .app import build_orchestrator, run_orchestrator
from .orchestrator import Orchestrator
from .players import PlayerRegistry
from .session import ConversationSession
from .switch import MasterSwitch

__all__ = [
    "Orchestrator", "ConversationSession", "MasterSwitch", "PlayerRegistry",
    "build_orchestrator", "run_orchestrator",
]
