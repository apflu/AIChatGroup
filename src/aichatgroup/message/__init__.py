"""前台平面：消息流（纯文本，不碰 tool）。

子包：
- conductor: 谁说话 + 编排 beat（原 director）
- generator: 一个 turn 的生成（组装→调用→解析→气泡）
- delivery:  演出（节奏、队列、交错、抢占）
- prompt:    消息侧分层 prompt 组装
模块：
- usher:     用户输入台口分流（absorb / user_forced）
"""
from .usher import Usher, UsherDecision

__all__ = ["Usher", "UsherDecision"]
