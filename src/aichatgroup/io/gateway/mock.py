"""离线 Mock 网关：按脚本返回台词，并忠实模拟前缀缓存。

在每个可缓存块边界记录哈希，重复的最长前缀记为 cache_read、新增部分记为
cache_creation——用于离线验收「warm 调用命中缓存」。脚本按**角色名**匹配：
从 tail 的人设句「扮演的角色是「X」」认出角色 X，弹出其下一句台词。
不改动 ModelGateway 协议、不污染真实 prompt。
"""
from __future__ import annotations

import hashlib
import re

from ...domain.types import GatewayResponse, Usage
from .base import block_text, est_tokens

# 与 Agent.render_persona() 的措辞对应，供 MockGateway 从 tail 里认出当前角色。
_PERSONA_NAME_RE = re.compile(r"扮演的角色是「(.+?)」")


class MockGateway:
    def __init__(self) -> None:
        # 已写入缓存的「前缀边界哈希」集合，模拟 Anthropic 后端的哈希比对。
        self._cache_hashes: set[str] = set()
        # 每个角色名的台词队列
        self._scripts: dict[str, list[str]] = {}
        self._fallback = "（……）"

    def push_script(self, agent_name: str, lines: list[str]) -> None:
        self._scripts.setdefault(agent_name, []).extend(lines)

    # -- 缓存模拟 --------------------------------------------------------
    def _cacheable_units(self, system: list[dict], messages: list[dict]) -> list[str]:
        """可缓存前缀 = 全部 system 块 + 除尾部外的所有历史消息。"""
        units = [block_text(b) for b in system]
        # messages[-1] 是每轮可变的 tail，不参与缓存
        for m in messages[:-1]:
            units.append(block_text(m["content"]))
        return units

    def _simulate_cache(self, units: list[str]) -> tuple[int, int]:
        """返回 (cache_read_tokens, cache_creation_tokens)。

        沿单元边界累计哈希：命中缓存的最长前缀记为 read，其余记为 creation，
        并把所有新边界哈希写入缓存集合。历史增长时，旧前缀被 read、新增块被 creation。
        """
        read = 0
        creation = 0
        running = hashlib.sha256()
        matched_prefix = True
        for unit in units:
            running.update(unit.encode("utf-8"))
            running.update(b"\x00")  # 边界分隔
            digest = running.hexdigest()
            tok = est_tokens(unit)
            if matched_prefix and digest in self._cache_hashes:
                read += tok
            else:
                matched_prefix = False
                creation += tok
                self._cache_hashes.add(digest)
        return read, creation

    # -- 主接口 ----------------------------------------------------------
    def complete(
        self,
        system: list[dict],
        messages: list[dict],
        model_id: str,
        max_tokens: int = 1024,
    ) -> GatewayResponse:
        tail_text = block_text(messages[-1]["content"]) if messages else ""
        match = _PERSONA_NAME_RE.search(tail_text)
        agent_name = match.group(1) if match else ""

        read, creation = self._simulate_cache(self._cacheable_units(system, messages))

        queue = self._scripts.get(agent_name, [])
        text = queue.pop(0) if queue else self._fallback

        usage = Usage(
            input_tokens=est_tokens(tail_text),
            output_tokens=est_tokens(text),
            cache_read_input_tokens=read,
            cache_creation_input_tokens=creation,
        )
        return GatewayResponse(text=text, usage=usage)
