"""Prompt 组装层：分层 build_prompt / build_tail + 各层散文渲染（world / layer1 / persona）。"""
from .builder import build_prompt, build_tail, render_layer1, render_persona, render_world

__all__ = ["build_prompt", "build_tail", "render_world", "render_layer1", "render_persona"]
