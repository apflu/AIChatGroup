"""演出：气泡的微观时序（节奏）+ 单消费者队列（抢占）+ 逐条投递（按 kind 分流、回复寻址）。

交错 / 剧本化打断：在 `QueuedBubble` 上加偏序边、消费改拓扑排序即可，接口留位（docs/message-ordering.md）。
"""
from .pacing import infer_pause, resolve_pauses
from .perform import TRAIL_OFF_NOTE, perform_queue, perform_turn, resolve_reply_target
from .queue import DeliveryQueue, QueuedBubble

__all__ = [
    "DeliveryQueue",
    "QueuedBubble",
    "TRAIL_OFF_NOTE",
    "infer_pause",
    "perform_queue",
    "perform_turn",
    "resolve_pauses",
    "resolve_reply_target",
]
