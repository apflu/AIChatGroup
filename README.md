# 多模型 AI 群聊引擎

多个 Agent 用不同模型（Opus / Sonnet / Haiku 等）在同一个群里吵吵闹闹，遵守世界书、
有导演调度、有开关键。核心引擎 **transport-agnostic**，首个落地面是多个 Telegram bot，
后续支持 FoundryVTT。设计论证见 [spec_claude_20260707.md](spec_claude_20260707.md)，
落地计划见 `~/.claude/plans/transient-discovering-wilkinson.md`。

当前进度：**M1 —— Telegram 多 bot 热闹群聊**（在 M0 引擎骨架上加：Transport 抽象、
异步 Orchestrator 主循环、Director 调度、开关键、SQLite 持久化、基础 compaction、
Telegram 落地面）。M0 骨架（Model Gateway / 分层 Prompt Builder / 单角色单调用多气泡 +
记忆增量）继续沿用。

## 快速开始

```bash
# 跑测试（uv 临时装 pytest + anthropic）
uv run --with pytest --with anthropic python -m pytest -q

# 离线回放演示（MockGateway，无需 API key，可复现）
uv run --with anthropic python scripts/replay_demo.py --turns 6

# 真实调用（需 ANTHROPIC_API_KEY，见 .env.example）
uv run --with anthropic python scripts/replay_demo.py --live --turns 6
```

离线回放的日志会打印每回合的 `cache_read` / `cache_creation`：首回合冷启动写缓存，
其后 warm 回合命中缓存读——这正是分层 Prompt 布局要验证的目标。

## M1 · Telegram 上线

```bash
# 1) BotFather 建 1 个观察者 bot + 每个角色各 1 个 bot；观察者务必 /setprivacy → Disable
# 2) 把所有 bot 拉进同一个群，拿到 chat_id；填好 .env（见 .env.example）与预设 JSON
# 3) 运行（懒加载 python-telegram-bot）
uv run --with anthropic --with python-telegram-bot \
  python scripts/run_telegram.py --preset examples/room.example.json
```

群里 `/pause` 暂停自动 chatter、`/resume` 恢复、`/stop` 停机；人类照常插话即被摄入调度。
**摄入与发送分离**：观察者 bot 收群里人类消息形成唯一共享历史，角色 bot 只负责发
（Telegram 规则下 bot 收不到别的 bot 的消息，角色发言由引擎直接入历史，天然不重复）。

## 代码结构（`src/aichatgroup/`）

> **按用途分包**（package-by-purpose），依赖方向无环、`message` 与 `story` 互不直接 import。
> 布局与依据见 [docs/architecture.md](docs/architecture.md)，消息排序/偏序/拓扑见 [docs/message-ordering.md](docs/message-ordering.md)。

| 子包 / 模块 | 职责 |
| --- | --- |
| `domain/` | 共享内核：`types.py`（`Message`/`ContentPart`/`WorldBook`/`Agent`/`RoomState` ...）+ `markers.py`（控制标记词表） |
| `message/conductor/` | 编导（原 director）：`rule.py`（RoundRobin，离线）、`model.py`（`ModelDirector`，Haiku 决定谁说话） |
| `message/generator/` | 生成回合：`turn.py`（发言回合）、`parsing.py`（多气泡+记忆增量） |
| `message/delivery/` | 演出：`pacing.py`（气泡节奏）；后续加交错队列 + 抢占 |
| `message/prompt/` | `builder.py`：分层 Prompt 组装 + 显式 `cache_control` 断点 |
| `story/memory/` | `compaction.py`：历史压缩（暗线平面唯一已落地块；storyteller / sim 待建） |
| `io/gateway/` | Model Gateway：`base.py`、`anthropic_gateway.py`、`openai_gateway.py`（含兼容端点）、`gemini_gateway.py`、`router.py`（按 model_id 分发）、`factory.py`（按 key 装配）、`mock.py` |
| `io/transport/` | 收发边界：`base.py`（`Transport` 协议）、`memory.py`（测试）、`telegram.py`（M1 落地，懒加载 ptb） |
| `io/persistence/` | `store.py`：SQLite 会话状态（历史去重 / 记忆快照 / 摘要） |
| `runtime/` | 编排层：`orchestrator.py`（异步 tick 主循环）、`switch.py`（开关键）、`telegram_app.py`（装配） |
| `presets.py` | 房间预设加载（手写世界书 + 角色卡，见 `examples/room.example.json`） |
| `observability.py` | 结构化事件流：`log_event(kind, **fields)`（ingest/schedule/model_call/compaction/error） |
| `config.py` / `logging_setup.py` | 跨层基础设施：配置与日志 |

常用符号在顶层再导出：`from aichatgroup import Agent, Orchestrator, ModelDirector, Store, load_preset`。

### M1 主循环（transport-agnostic）

`Orchestrator` 用 asyncio 把两条协程跑在一起：`_ingest_loop`（摄入人类/外部消息，按
`external_id` 去重入库）与 `_speak_loop`（Director 选下一个说话者 → 组装 prompt → 调模型 →
按气泡节奏 typing+发送 → 记忆增量入库）。**只有网络调用 `gateway.complete` 下放线程池**，
prompt 组装/解析/历史读写全在事件循环线程内完成，两条协程对 `RoomState` 无并发竞争。
Telegram 只是实现了 `Transport` 协议的一层薄适配；Foundry（M5）复用同一接口。

## 多 provider（每个角色一套模型，可混用）

`gateway/` 是多套适配器 + 一个路由器。规范线格式是「Anthropic 形状」（system block +
`cache_control` 断点），每个非 Anthropic 适配器把它翻译成自家格式（丢掉断点、只取文本）：

| 适配器 | 覆盖 | 缓存字段来源 |
| --- | --- | --- |
| `AnthropicGateway` | `claude-*` | 显式断点，`usage.cache_read/creation` |
| `OpenAIGateway` | `gpt-*`/`o1..o4`，及**任意 OpenAI 兼容端点**（DeepSeek/Groq/OpenRouter/本地 vLLM，靠 `base_url`） | 自动前缀缓存，`prompt_tokens_details.cached_tokens` |
| `GeminiGateway` | `gemini-*` | `usage_metadata.cached_content_token_count` |

**模型选择的规范形式是 `provider_alias#model`**，别名与模型名解耦：

```
anthropic#claude-opus-4-8      openai#gpt-4o      gemini#gemini-2.0-flash
deepseek#deepseek-chat         # deepseek 是自定义的兼容端点别名
```

`RouterGateway` 只看 `#` 前的别名分发（换 provider 只改别名、不动模型名；同一模型名可挂在
不同端点上互不影响），自身也实现 `ModelGateway` 协议 → engine / Orchestrator **完全不用改**。
不带 `#` 的裸模型名仍按前缀推断路由（向后兼容）。于是角色卡里给不同角色写不同 `model_id` 即可混用多家。

**新增一个 provider（声明式）**：写一个 `providers.json`（放项目根自动加载，或 `AICG_PROVIDERS_FILE`
指定；见 `examples/providers.example.json`），每个 provider 一个块——正是你要的形状：

```json
{ "providers": [
  { "alias": "deepseek", "type": "openai",
    "provider_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY" }
] }
```

`type` = `openai`/`anthropic`/`gemini`（`openai` 覆盖一切兼容端点），`provider_url` 是端点地址，
`api_key_env` 指向 `.env` 里的密钥变量名（密钥不进配置文件）。预设 JSON 也可内嵌同样的 `providers`
数组。装配是**懒实例化**：某家 key 在环境里、但没装它的 SDK、又从没路由到它时，不会拖垮启动——
只有真正拿它发消息才会因缺包报错。内置 `anthropic`/`openai`/`gemini` 仍由标准 key 自动登记。

## 分层 Prompt 布局（M0 共享全知）

```
system:
  [第0层 世界观圣经 + 群聊规则]        ← cache breakpoint 1
  [第1层 长期摘要 + 客观关系图谱]      ← cache breakpoint 2
messages:
  [第2层 共享历史，逐条 user 消息，append-only]
      └─ 最后一条历史消息            ← 滚动 cache breakpoint 3
  [第3层尾部 人设 + 私有记忆 + 导演指令 + 输出契约]  ← 不缓存
```

共享块前置、人设沉尾，使 `system + 历史` 前缀对所有 Agent 逐字节相同 → 命中同一缓存条目。
硬规则：永远不让一个模型生成不归它管的角色内容。

## 消息模型（围绕消息的可靠抽象）

共享历史里每条是一个 `Message`（粒度 = **一条气泡**）：`id`（房间内稳定单调，既是持久主键、
也是模型回复寻址的 handle）、`speaker`、`parts`（动作/语言分离）、`reply_to`（指向另一条 id）、
`meta`（`external_id`/… 开放逃生舱）。渲染进历史为 `⟦id⟧ [speaker] （回…）（动作）语言`——
`⟦id⟧`/`speaker`/`parts` 都跨 agent 相同、跨轮稳定，故前缀逐字节一致，**共享缓存不变式不破**。

## 输出契约

被点名的角色一次调用输出 1~3 条气泡：

- 相邻两条之间用 `{{SEPARATOR}}` 分隔（可带秒数 `{{SEPARATOR:2}}`）；
- **动作/神态**用 `*…*` 或 `{{ACTION}}…{{/ACTION}}` 包裹，其余为台词——引擎归一成 `parts`；
- **回复某条**：气泡首写 `{{REPLY:37}}` 表示回复历史里 `⟦37⟧`。人类用 Telegram「回复」时，
  被回复消息的引用也会传入；目标若已滑出近窗，引擎从 store 取回**内联重注入**一次；
- 末尾可追加 `{{MEMORY}}` + 一段 JSON 作为记忆增量，引擎合并进该角色私有快照。

控制标记词表集中在 [markers.py](src/aichatgroup/domain/markers.py)，解析对大小写/空白容忍，
剥掉模型误补的闭合标记（`{{/MEMORY}}` / 旧式 `</MEMORY>`）与误回显的 `⟦id⟧`/自名前缀，并有
fuzz 测试守护。用 `{{…}}` 而非 `<<…>>`：尖括号诱发「XML 要闭合」本能弄脏 JSON，双花括号既避开
这点、又与 SillyTavern 宏一致。**agentic/tool 不进消息流**——留给 storyteller/sim 等暗线模块在
各自私有上下文里自理。

> **Prompt 结构方向**：PromptBuilder 会逐步向 SillyTavern 预设结构靠拢（命名 prompt 片段 +
> 顺序/开关 + marker 占位 + 深度注入，见 `preset/example.json`），并支持导入 SillyTavern 预设
> 来控制模型行为——预设不替代 Builder，只提供结构与文案。当前四层组装是该模型的一个特例。

## 气泡节奏（与性格接驳）

气泡之间的停顿由 [pacing.py](src/aichatgroup/engine/pacing.py) 推断，结果放在 `TurnResult.pauses`，
供 M1 的 Telegram 发送层（typing 提示 + sleep）消费。两条来源：

- **模型显式**：分隔符可带秒数 `{{SEPARATOR:2}}`；
- **缺省推断**：无显式值时按下一条气泡长度估算。

**原则**：一切涉及推断的行为都要留有与角色性格接驳的口子——把可调 factor 存进**角色设定**。
停顿是第一个落点：每个 `Agent` 带一个 `PacingConfig`（`per_char_s` / `explicit_scale` 等），
急性子停得短、慢性子停得长。后续新增的推断行为应循同一模式挂到角色上。

## 路线图

- ~~**M0** 引擎骨架~~ ✅
- ~~**M1（MVP）** Telegram 多 bot 热闹群聊：Transport 抽象、异步 Orchestrator、Director 调度器、
  手写世界书/角色卡、开关键、SQLite 持久化、基础 compaction~~ ✅（已实机验证）
- ~~**消息抽象地基**（M1↔M2）：`Message` 域模型（稳定 id/parts/reply_to/meta）、动作/语言分离、
  回复寻址端到端、结构化事件日志~~ ✅
- **M2** Storyteller（编导/压力源，暗线模块保留私有上下文自行思考）+ 更强记忆。
- **M3** 知识隔离。 **M4** 世界书生成 + RAG。 **M5** FoundryVTT 支持。
