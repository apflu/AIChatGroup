"""Conductor 编导：决定下一个说话者（后续升级为编排整拍 beat）。

历史名 Director；接口暂保持 `next_speaker`，Beat 编排能力后续在此层扩展。
"""
from .base import Director, consecutive_count, last_speaker_name
from .model import ModelDirector
from .rule import RoundRobinDirector

__all__ = [
    "Director",
    "ModelDirector",
    "RoundRobinDirector",
    "consecutive_count",
    "last_speaker_name",
]
