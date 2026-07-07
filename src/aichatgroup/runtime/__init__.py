"""运行时编排层：主循环 + 开关键 + Telegram 装配入口。"""
from .orchestrator import Orchestrator
from .switch import MasterSwitch
from .telegram_app import build_orchestrator, serve

__all__ = ["Orchestrator", "MasterSwitch", "build_orchestrator", "serve"]
