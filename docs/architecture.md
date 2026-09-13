# 架构与模块蓝图

> 姊妹篇 [message-ordering.md](message-ordering.md) 讲"消息如何排序"。本文讲"代码如何分层",
> 以及 **package-by-purpose(按用途分包)** 的文件夹蓝图。核心判据是**依赖方向**,不是名字好听。

---

## 1. 平行架构

- **前台:消息流(message)** —— 负责文本生成的agent将产出气泡(语言/动作/sticker)、回复动作、(剧本化的)打断。
- **后台:故事(story)** —— storyteller / sim / 记忆。各自保留**私有上下文**、自行分步思考,
  只把**影响**注入前台 agent 的尾部。agentic 复杂度隔离在暗线内部,**不进消息流**。

两边**不直接互相通信**:它们通过 `domain` 里的数据(BeatBrief、注入尾部的文本)通信,由 `runtime` 接线。

## 2. 流水线:Plan → Generate → Perform

```
Storyteller(暗线, TODO) ──► StoryFramework / BeatBrief
        │
Conductor(编导) ──► BeatPlan：谁上场、交错/打断走位(= 作者气泡 DAG)、宏观间隔
        │
Generator(生成) ──► 每个 turn 跑一次：build_prompt → 模型 → parse → Bubbles[]（parts + hint + DAG 边）
        │
Delivery(演出) ──► 偏序队列 + 安排排序拓扑 + 微观时序 + 规划抢占 ──► 驱动 transport
        │
Orchestrator(运行时) ──► 链接 + loop / 持久化 / 开关 / compaction
```

三个权威互不越界(详见 message-ordering §9):**Conductor 定结构,模型填内容,Delivery 安排拓扑、排序、演出。**

## 3. 文件夹蓝图

按**用途**分五个顶层组,判据是每组的依赖方向清晰、职责单一:

```
aichatgroup/
├── domain/                # 【共享内核】谁都依赖它，它不依赖任何人（纯数据；lint-imports 强制）
│   ├── types.py           #   Message / ContentPart / RoomState / Agent / WorldBook / TurnResult
│   ├── markers.py         #   标记词表（模型 ↔ Delivery 的契约）
│   ├── commands.py        #   ✅ 控制指令词表（/pause … /iam）：transport 标 is_command、runtime 分派，同一份
│   ├── conversation.py    #   ✅ ConversationIntent / ConversationEnd + reason/kind 词表（storyteller⇄conductor 契约）
│   ├── player.py          #   ✅ Player + 世界名净化
│   ├── ordering.py        #   ★TODO 偏序/DAG：BubbleGraph、depends_on、topological_sort
│   └── beat.py            #   ★TODO BeatPlan / SpeakIntent（编排的数据结构，非逻辑）
│
├── prompts/               # 【文本资产】整段 prompt：system+user 模板 + world/tail/persona 片段（*.md）
│                          #   运行时数据用 $slot 回填（string.Template，字面 {{marker}}/{json} 免转义）。
│                          #   loader 无 import 依赖；"数据 → 散文"的渲染函数在 message/prompt/builder（domain 不碰它）。
│                          #   机器契约（marker 值/DIRECTIONS/none/MockGateway 正则）仍是代码常量，留解析器身边，靠 test 防漂移。
│
├── message/               # 【前台】消息流
│   ├── conductor/         #   ✅ 谁说话（Conductor）+ 会话结束检测
│   │   ├── base.py  rule.py  model.py  end_detector.py
│   ├── generator/         #   ✅ 一个 turn：prepare_turn → 模型 → finish_turn → GeneratedTurn（在线/离线同一份）
│   │   ├── turn.py  parsing.py
│   ├── delivery/          #   演出：微观时序 + 逐条投递（perform）；★队列、交错、抢占待建
│   │   ├── pacing.py  perform.py  [queue.py  interrupt.py]
│   ├── prompt/            #   消息侧分层 prompt + 各层散文渲染
│   │   └── builder.py
│   └── usher/             #   ✅ 用户输入台口分流（absorb / user_forced）
│       └── model.py
│
├── story/                 # 【后台】故事（各自私有上下文，只注入前台尾部）
│   ├── storyteller/       #   ✅ 会话级编导/注入对话压力：会话边界播种 ConversationIntent
│   │   ├── base.py        #     Storyteller 协议 + StubStoryteller（零模型骨架）
│   │   └── model.py       #     ModelStoryteller（重模型，读 last_end 播种 KIND/HOOK）
│   ├── memory/            #   记忆 / 压缩
│   │   └── compaction.py
│   └── sim/               #   ★TODO 模拟经营数值系统
│
├── io/                    # 【出站适配】和外部世界打交道
│   ├── gateway/           #   模型 provider 适配 + 路由 + ask（便宜模型一问一答的统一入口）
│   ├── transport/         #   收发边界：memory / telegram（平台 reply 限制 can_reply_natively 在这）
│   └── persistence/       #   SQLite 存储 + RoomRepository（内存近窗 + 库的唯一写入口）
│
├── runtime/               # 【编排/运行时】把前台和后台接起来
│   ├── orchestrator.py    #   只接线 + loop：ingest / speak 两协程
│   ├── session.py         #   ✅ ConversationSession：会话状态机（seed/end/user_forced/清洗队列）
│   ├── players.py         #   玩家身份注册表 + 摄入侧身份解析 / /iam
│   ├── app.py             #   transport 无关装配：build_orchestrator(preset, settings, transport)
│   ├── telegram_app.py    #   Telegram 入口（= aichatgroup-serve）
│   ├── log_relay.py       #   EventLogRelay：事件流 → transport.send_system
│   └── switch.py
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

以上规则由 `uv run lint-imports` 强制(契约写在 `pyproject.toml [tool.importlinter]`):
domain 不 import 兄弟包、message⊥story、无人依赖 runtime、io 不依赖 message/story。

## 5. 现状 → 蓝图 的迁移映射(已完成)

| 原位置 | 现位置 | 理由 |
| --- | --- | --- |
| `message/orchestrator/orchestrator.py` | `runtime/orchestrator.py` | orchestrator 接**两个平面**,不属 message 专有 |
| `story/engine/parsing.py` | `message/generator/parsing.py` | 解析模型输出是**生成**动作,属前台 |
| `story/engine/turn.py` | `message/generator/turn.py` | turn 执行属前台生成 |
| `story/engine/pacing.py` | `message/delivery/pacing.py` | 节奏是**演出**微观时钟,属前台 |
| `story/engine/compaction.py` | `story/memory/compaction.py` | 记忆压缩是**唯一**真正属暗线的一块 |
| `message/director/` | `message/conductor/` | 名字随职责升级(不只是选人,而是编 beat);`Director*` 别名已移除 |
| orchestrator 的发送段 | `message/delivery/perform.py` | 演出属前台;平台 reply 限制下沉到各 transport |
| orchestrator 的会话状态机 | `runtime/session.py` | 一个类管 seed/end/user_forced/清洗队列,循环只在三个点碰它 |
| orchestrator 的 store 双写 | `io/persistence/room_repo.py` | 写一次;离线/在线差别只在 repo 里 |
| `domain.types` 的 `render*` 方法 | `message/prompt/builder.py` | domain 回到纯数据,不再 import prompts |
| `presets.TelegramConfig` | `io/transport/telegram.py` | 预设格式 transport 无关,各 transport 自取自己的段 |

> **关于 `io/`**:把 gateway/transport/persistence 收进 `io/` 更"按用途",但给稳定代码加了一层嵌套。
> 若你更看重浅层级,把这三个留在顶层平铺也完全可以 —— 这层纯属口味,不影响依赖规则。

## 6. 数据契约草图(草案)

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
| ✅ `_speak` 复用 generator(消掉两份真相:prepare/finish_turn) | message/generator | 已落地 |
| 拆宏观/微观两个钟到 conductor/delivery | 两个占位模块 | 现在 |
| 偏序气泡队列(先全序,结构支持交错) | message/delivery/queue.py | 现在留位 |
| 用户打断:判断器 + 抢占 | message/delivery/interrupt.py + conductor | 用户路径**必做**,可紧接队列 |
| AI 剧本化交错/打断 | conductor 作者 edges | 后置(填进已就位的接缝) |
| ✅ storyteller 会话边界播种意图 → conductor_instruction 尾部注入 | story/storyteller + message/prompt | M2 已落地 |
| 高级 marker 词表 | domain/markers | 随 delivery 一起长 |

第一原则不变:核心引擎 **transport-agnostic**;硬规则:永远不让一个模型生成不归它管的角色内容。
