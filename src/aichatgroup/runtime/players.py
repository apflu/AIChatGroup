"""PlayerRegistry —— 某个世界（room_id）内的玩家身份注册表。

`(channel, external_id) -> Player`。锚稳定外部 id、不锚显示名。按世界分区（不进全局），
不同世界各起各的、天然隔离、便于测试。store 可选：给了就持久化 + 启动时载入，
没给就纯内存（离线/测试）。

校验哲学（见 docs 讨论）：**不追硬唯一性**（世界内名字无法枚举，如只活在世界书正文里的 NPC），
靠 `Message` 渲染的 `<user>` 结构 tag 兜底区分人/AI。这里只做两件可解的事：
1. **净化**（domain.sanitize_player_name）——防伪造归属，必做；
2. **软查重**——名字若精确撞上**可枚举的正式班底**（本世界 agent 名 + 已注册玩家名）就打回，
   纯 UX，不追完备。
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..domain.player import STRANGER_NAME, Player, sanitize_player_name
from ..observability import log_event

if TYPE_CHECKING:
    from ..io.persistence import Store
    from ..io.transport.base import InboundMessage

logger = logging.getLogger(__name__)


class PlayerRegistry:
    def __init__(
        self,
        store: Store | None = None,
        room_id: int | None = None,
        agent_names: Iterable[str] = (),
    ) -> None:
        self._store = store
        self._room_id = room_id
        self._agent_names = set(agent_names)
        self._by_ext: dict[tuple[str, str], Player] = {}
        if store is not None and room_id is not None:
            for r in store.list_players(room_id):
                p = Player(
                    name=r.name, persona=r.persona, channel=r.channel, external_id=r.external_id,
                )
                self._by_ext[(p.channel, p.external_id)] = p

    def resolve(self, channel: str, external_id: str) -> Player | None:
        return self._by_ext.get((channel, external_id))

    def _name_taken(self, name: str, exclude: tuple[str, str]) -> bool:
        if name in self._agent_names:
            return True
        return any(
            key != exclude and p.name == name for key, p in self._by_ext.items()
        )

    def register(
        self, channel: str, external_id: str, name: str, persona: str = ""
    ) -> Player:
        """注册/改名（/iam）。净化 → 软查重 → 落库。非法或撞名抛 ValueError。"""
        clean = sanitize_player_name(name)
        key = (channel, external_id)
        if self._name_taken(clean, exclude=key):
            raise ValueError(f"名字已被占用：{clean}")
        # 改名时保留原人设（除非显式给了新的）
        if not persona and key in self._by_ext:
            persona = self._by_ext[key].persona
        player = Player(name=clean, persona=persona, channel=channel, external_id=external_id)
        self._by_ext[key] = player
        if self._store is not None and self._room_id is not None:
            self._store.upsert_player(self._room_id, channel, external_id, clean, persona)
        return player

    def seed(self, entries: Iterable[tuple[str, str, str, str]]) -> None:
        """预设预登记：entries = [(channel, external_id, name, persona), ...]。已存在则跳过。"""
        for channel, external_id, name, persona in entries:
            if not external_id or (channel, external_id) in self._by_ext:
                continue
            try:
                self.register(channel, external_id, name, persona)
            except ValueError as exc:
                logger.warning("预登记玩家失败（%s）：%s", name, exc)

    def names(self) -> set[str]:
        return {p.name for p in self._by_ext.values()}


# ---- 摄入侧的身份解析 / 认领（Orchestrator 调用）---------------------------

def resolve_speaker(players: PlayerRegistry | None, msg: InboundMessage) -> str:
    """把发送者解析成世界内显示名。无注册表→原显示名（旧行为）；有表但未注册→陌生人。"""
    if players is not None and msg.sender_id:
        player = players.resolve(msg.channel, msg.sender_id)
        return player.name if player is not None else STRANGER_NAME
    return msg.speaker


def claim_name(players: PlayerRegistry | None, msg: InboundMessage) -> Player | None:
    """`/iam <世界名>`：把发送者的稳定 id 绑到一个世界名（含净化/软查重）。失败返回 None（已记 event）。"""
    if players is None or not msg.sender_id:
        return None
    parts = msg.text.split(" ", 1)
    name = parts[1].strip() if len(parts) > 1 else ""
    if not name:
        log_event("player_iam_rejected", channel=msg.channel, reason="空名字")
        return None
    try:
        player = players.register(msg.channel, msg.sender_id, name)
    except ValueError as exc:
        log_event("player_iam_rejected", channel=msg.channel, name=name, reason=str(exc))
        return None
    logger.info("玩家认领世界名：%s", player.name)
    log_event("player_register", name=player.name, channel=msg.channel)
    return player
