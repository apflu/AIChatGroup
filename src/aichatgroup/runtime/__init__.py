"""运行时编排层：主循环 + 开关键 + 玩家身份注册表 + Telegram 装配入口。"""
from .orchestrator import Orchestrator
from .players import PlayerRegistry
from .switch import MasterSwitch
from .telegram_app import build_orchestrator, serve

__all__ = ["Orchestrator", "MasterSwitch", "PlayerRegistry", "build_orchestrator", "serve"]
