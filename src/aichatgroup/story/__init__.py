"""后台平面：暗线模块（各自私有上下文，只把影响注入前台尾部）。

子包：
- memory:      记忆 / 压缩
- storyteller: 会话级编导 / 压力源（会话边界播种 ConversationIntent）
- sim:         模拟经营数值系统（TODO）
"""
from .storyteller import ModelStoryteller, Storyteller, StubStoryteller

__all__ = ["Storyteller", "StubStoryteller", "ModelStoryteller"]
