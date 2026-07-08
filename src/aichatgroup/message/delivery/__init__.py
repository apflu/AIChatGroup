"""演出：气泡的微观时序（节奏），后续加交错队列与抢占。"""
from .pacing import infer_pause, resolve_pauses

__all__ = ["infer_pause", "resolve_pauses"]
