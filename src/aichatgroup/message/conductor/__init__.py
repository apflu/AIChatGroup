"""Conductor 编导：beat 级时钟——决定下一个说话者 + 检测会话该不该结束。

M2 起统一命名为 **Conductor**（历史名 Director 保留一个迁移周期的别名）。
`next_speaker` 排 beat；`EndDetector` 依 beat 观测判会话收束并报 reason（喂回 storyteller）。
"""
from .base import Conductor, Director, consecutive_count, last_speaker_name
from .end_detector import (
    EndDetector,
    FlatTensionReader,
    StagnationTensionReader,
    TensionReader,
)
from .model import ModelConductor, ModelDirector
from .rule import RoundRobinConductor, RoundRobinDirector

__all__ = [
    # 编导（选人）
    "Conductor",
    "ModelConductor",
    "RoundRobinConductor",
    # 迁移期别名
    "Director",
    "ModelDirector",
    "RoundRobinDirector",
    # 会话结束检测
    "EndDetector",
    "TensionReader",
    "FlatTensionReader",
    "StagnationTensionReader",
    # 辅助
    "consecutive_count",
    "last_speaker_name",
]
