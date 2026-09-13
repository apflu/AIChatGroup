"""DeliveryQueue —— 单消费者气泡队列 + 抢占（docs/message-ordering.md §7 / §8）。

并发不变式（§8）：生成在线程池里只产结果，**入队 / 出队 / 抢占全在事件循环线程**；单写单读，无锁。
抢占 = 循环线程调用 `abort()`：清掉尚未发出的 pending，并把 **beat 代号** +1。

beat 代号是"这批气泡属于哪一拍"的戳：
- 生成开始前取 `queue.beat`；生成回来后 `push(..., beat=那个戳)`——若期间被抢占（戳已过期），
  整批直接丢弃（`beat_aborted stage=generate`）：MVP 让在飞的生成跑完再扔，不做 cancellation token。
- 演出侧每条气泡**发送前**再核一次戳（`is_stale`）：抢占落在 typing 等待期间的，那条也不发。

当前是**全序**（deque）：偏序边 / 交错 留位在 `QueuedBubble` 上加字段，消费顺序换成拓扑排序即可，
调用方接口不变。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ...domain.types import Agent
from ...observability import log_event
from ..generator.parsing import ParsedBubble


@dataclass
class QueuedBubble:
    agent: Agent
    bubble: ParsedBubble
    pause: float            # 发送前应等待的秒数（微观时钟，已由 pacing 解析）
    beat: int               # 所属 beat 代号；与队列当前代号不符即视为已抢占


class DeliveryQueue:
    def __init__(self) -> None:
        self._items: deque[QueuedBubble] = deque()
        self._in_flight: QueuedBubble | None = None   # 已出队、正在等节奏 / 发送的那条
        self.beat = 0                                 # 当前 beat 代号；abort 时 +1
        self.aborts = 0                               # 累计抢占次数（观测用）

    # ---- 生产（循环线程）--------------------------------------------------
    def push(self, agent: Agent, bubbles: list[ParsedBubble], pauses: list[float], *, beat: int) -> bool:
        """把一个回合的气泡整批入队。beat 戳已过期（生成期间被抢占）→ 丢弃整批，返回 False。"""
        if beat != self.beat:
            log_event("beat_aborted", stage="generate", agent=agent.name, dropped=len(bubbles))
            return False
        for pb, pause in zip(bubbles, pauses, strict=True):
            self._items.append(QueuedBubble(agent, pb, pause, beat))
        return True

    # ---- 消费（循环线程）--------------------------------------------------
    def pop(self) -> QueuedBubble | None:
        item = self._items.popleft() if self._items else None
        self._in_flight = item
        return item

    def done(self, item: QueuedBubble) -> None:
        """消费方发完（或决定丢弃）一条后调用，释放 in-flight 标记。"""
        if self._in_flight is item:
            self._in_flight = None

    def is_stale(self, item: QueuedBubble) -> bool:
        return item.beat != self.beat

    # ---- 抢占（循环线程）--------------------------------------------------
    def abort(self, *, reason: str = "") -> int:
        """清空 pending、beat 代号 +1。返回被丢弃的气泡数（含正在等节奏的那条，它发送前会自查到过期）。"""
        dropped = len(self._items) + (1 if self._in_flight is not None else 0)
        agent = (self._in_flight or (self._items[0] if self._items else None))
        self._items.clear()
        self.beat += 1
        self.aborts += 1
        log_event(
            "beat_aborted", stage="perform", reason=reason or None,
            agent=agent.agent.name if agent is not None else None, dropped=dropped,
        )
        return dropped

    def __len__(self) -> int:
        return len(self._items)

    @property
    def idle(self) -> bool:
        """没有 pending 也没有 in-flight。"""
        return not self._items and self._in_flight is None
