"""生成：一个角色的一个发言回合 → 气泡 + 记忆增量。"""
from .parsing import ParsedBubble, parse_turn_output
from .turn import merge_memory, run_turn

__all__ = ["ParsedBubble", "parse_turn_output", "merge_memory", "run_turn"]
