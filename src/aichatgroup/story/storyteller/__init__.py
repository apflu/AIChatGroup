"""storyteller —— 会话级编导 / 压力源（暗线平面）。

会话边界事件驱动：seed / reseed 播种 ConversationIntent，不 mid-conversation 插手。
- StubStoryteller：固定闲聊，M2-A 骨架用（零模型）。
- ModelStoryteller：重模型，M2-C 真意图（张力 / 世界抗拒 / 定向回应）。
"""
from .base import Storyteller, StubStoryteller
from .model import ModelStoryteller

__all__ = ["Storyteller", "StubStoryteller", "ModelStoryteller"]
