# 架构与模块蓝图

> 姊妹篇 [message-ordering.md](message-ordering.md) 讲"消息如何排序"。本文讲"代码如何分层",
> 以及 **package-by-purpose(按用途分包)** 的文件夹蓝图。核心判据是**依赖方向**,不是名字好听。

---

## 1. 两平面架构

- **前台:消息流平面(message)** —— 文本生成 agent 产出气泡(语言 / 动作 / sticker)、回复、(剧本化)打断。
  纯文本模型,**不碰 tool**。
- **后台:暗线平面(story)** —— storyteller / sim / 记忆。各自保留**私有上下文**、自行分步思考,
  只把**影响**注入前台 agent 的尾部。agentic 复杂度隔离在暗线内部,**不进消息流**。

两平面**不直接互相 import**:它们通过 `domain` 里的数据(BeatBrief、注入尾部的文本)通信,由 `runtime` 接线。
这条"平面互不依赖"是整套结构优雅的根。

## 2. 流水线:Plan → Generate → Perform

```
Storyteller(暗线, TODO) ──► StoryFramework / BeatBrief
        │
Conductor(编导) ──► BeatPlan：谁上场、交错/打断走位(= 作者气泡 DAG)、宏观间隔
        │   ← 今天的 Director 是它的退化版(cast=1、无走位)
Generator(生成) ──► 每个 turn 跑一次：build_prompt → 模型 → parse → Bubbles[]（parts + hint + DAG 边）
        │
Delivery(演出) ──► 偏序队列 + 挑拓扑排序 + 微观时序 + 抢占 ──► 驱动 transport
        │
Orchestrator(运行时) ──► 只接线 + loop / 持久化 / 开关 / compaction，不再是 god-loop
```

三个权威互不越界(详见 message-ordering §9):**Conductor 定结构,模型填血肉,Delivery 挑拓扑排序演出。**

## 3. 文件夹蓝图(推荐)

按**用途**分五个顶层组,判据是每组的依赖方向清晰、职责单一:

```
aichatgroup/
├── domain/                # 【共享内核】谁都依赖它，它不依赖任何人
│   ├── types.py           #   Message / ContentPart / RoomState / Agent / WorldBook / TurnResult
│   ├── markers.py         #   标记词表（模型 ↔ Delivery 的契约）
│   ├── ordering.py        #   ★NEW 偏序/DAG：BubbleGraph、depends_on、topological_sort
│   └── beat.py            #   ★NEW BeatPlan / SpeakIntent（编排的数据结构，非逻辑）
│
├── prompts/               # 【文本资产】整段 prompt：system+user 模板 + world/tail/persona 片段（*.md）
│                          #   运行时数据用 $slot 回填（string.Template，字面 {{marker}}/{json} 免转义）。
│                          #   loader 无 import 依赖 → 谁都可 load/render（连 domain 都用它渲 persona），不产生平面耦合。
│                          #   机器契约（marker 值/DIRECTIONS/none/MockGateway 正则）仍是代码常量，留解析器身边，靠 test 防漂移。
│
├── message/               # 【前台平面】消息流（纯文本，不碰 tool）
│   ├── conductor/         #   谁说话 + 编排 beat（原 director/）
│   │   ├── base.py  rule.py  model.py
│   ├── generator/         #   一个 turn：组装→调用→解析→气泡（原 engine/turn + parsing）
│   │   ├── turn.py  parsing.py
│   ├── delivery/          #   ★演出：队列、交错、微观时序、抢占（原 pacing + orchestrator 的发送段）
│   │   ├── pacing.py  queue.py  interrupt.py
│   └── prompt/            #   消息侧分层 prompt（原 prompt/builder）
│       └── builder.py
│
├── story/                 # 【后台平面】暗线（各自私有上下文，只注入前台尾部）
│   ├── storyteller/       #   ★TODO 编导/压力源：产出 StoryFramework / BeatBrief
│   ├── memory/            #   记忆 / 压缩（原 engine/compaction）
│   │   └── compaction.py
│   └── sim/               #   ★TODO 模拟经营数值系统
│
├── io/                    # 【出站适配】和外部世界打交道（可选：嫌深就摊平回顶层）
│   ├── gateway/           #   模型 provider 适配 + 路由（不动内部）
│   ├── transport/         #   收发边界：memory / telegram（不动内部）
│   └── persistence/       #   SQLite 存储（不动内部）
│
├── runtime/               # 【编排/运行时】把两个平面接起来
│   ├── orchestrator.py    #   协调 conductor→generator→delivery + story 注入（原 message/orchestrator/）
│   ├── switch.py
│   └── telegram_app.py    #   入口装配
│
├── observability.py       # 横切：结构化事件流
├── config.py
└── logging_setup.py
```

## 4. 依赖方向规则(结构的真正约束)

允许的 import 方向(**无环**):

```
domain   ← 谁都可以依赖，它不 import 任何子包
io       ← 依赖 domain（实现 domain 里的协议）
message  ← 依赖 domain、io 的协议
story    ← 依赖 domain、io 的协议
runtime  ← 依赖以上全部（它负责接线）
（没有任何东西依赖 runtime）
```

**硬规则:`message` 与 `story` 互不直接 import。** 它们通过 `domain` 数据通信、由 `runtime` 装配。
一旦发现 `message/*` import 了 `story/*`(或反之),说明平面边界破了,该把中间物提到 `domain`。

## 5. 现状 → 蓝图 的迁移映射

你已经动过的两处,建议再校正:

| 现状 | 建议 | 理由 |
| --- | --- | --- |
| `message/orchestrator/orchestrator.py` | `runtime/orchestrator.py` | 单文件文件夹;且 orchestrator 接**两个平面**,不属 message 专有 |
| `story/engine/parsing.py` | `message/generator/parsing.py` | 解析模型输出是**生成**动作,属前台 |
| `story/engine/turn.py` | `message/generator/turn.py` | turn 执行属前台生成 |
| `story/engine/pacing.py` | `message/delivery/pacing.py` | 节奏是**演出**微观时钟,属前台 |
| `story/engine/compaction.py` | `story/memory/compaction.py` | 记忆压缩是**唯一**真正属暗线的一块 |
| `message/director/` | `message/conductor/` | 名字随职责升级(不只是选人,而是编 beat);别名保留一个迁移周期 |

其余(`domain` / `gateway` / `transport` / `persistence` / `prompt`)内部不动,只是可能被收进 `io/`。

> **关于 `io/`**:把 gateway/transport/persistence 收进 `io/` 更"按用途",但给稳定代码加了一层嵌套。
> 若你更看重浅层级,把这三个留在顶层平铺也完全可以 —— 这层纯属口味,不影响依赖规则。

## 6. 数据契约草图(草案,待拧)

放 `domain/`,是两平面 + runtime 的共享词汇。字段是**草稿**,等实现前再定死:

```python
# domain/beat.py
@dataclass
class SpeakIntent:
    agent_id: str
    kind: str = "normal"          # normal | interrupt | overlap
    truncate_after: int | None = None   # 被打断者：第几个气泡后截断/收尾
    # 生成期需要的上下文（剧本化打断时，插话者预知被切内容）由 Conductor 填

@dataclass
class BeatPlan:
    intents: list[SpeakIntent]    # 这一拍上场的人 + 走位
    edges: list[tuple[int, int]]  # 气泡级 DAG 的跨 turn 边（turn 内部边自动生成）
    macro_delay_s: float = 0.0    # 这一拍之前的宏观间隔（宏观时钟）

# domain/ordering.py
@dataclass
class BubbleGraph:
    # 节点 = 气泡；边 = depends_on（x 必在 y 前）
    def topological_orders(self) -> Iterator[list[Bubble]]: ...
    def one_valid_order(self) -> list[Bubble]: ...   # Delivery 默认取一个
```

`SpeakIntent.kind`、`BeatPlan.edges`、`BubbleGraph` 就是 message-ordering.md 里"作者 DAG"的落地形态。

## 7. 现在做 / 后置

| 项 | 落点 | 时机 |
| --- | --- | --- |
| `_speak` 复用 `run_turn`(消掉两份真相) | message/generator | **现在**,零风险纯重构 |
| 拆宏观/微观两个钟到 conductor/delivery | 两个占位模块 | 现在 |
| 偏序气泡队列(先全序,结构支持交错) | message/delivery/queue.py | 现在留位 |
| 用户打断:判断器 + 抢占 | message/delivery/interrupt.py + conductor | 用户路径**必做**,可紧接队列 |
| AI 剧本化交错/打断 | conductor 作者 edges | 后置(填进已就位的接缝) |
| storyteller 框架 → prompt | story/storyteller + message/prompt | 后置(开 M2 时连着设计) |
| 高级 marker 词表 | domain/markers | 随 delivery 一起长 |

第一原则不变:核心引擎 **transport-agnostic**;硬规则:永远不让一个模型生成不归它管的角色内容。
