"""Transport 层：核心引擎与外部世界（Telegram / Foundry / 测试）的收发边界。"""
from .base import InboundMessage, Transport
from .memory import InMemoryTransport
from .telegram import TelegramTransport  # 构造时才懒加载 python-telegram-bot

__all__ = ["InboundMessage", "Transport", "InMemoryTransport", "TelegramTransport"]
