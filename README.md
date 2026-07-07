# 多模型 AI 群聊引擎

多个 Agent 用不同模型（Opus / Sonnet / Haiku 等）在同一个群里吵吵闹闹，遵守世界书、
有导演调度、有开关键。核心引擎 **transport-agnostic**，首个落地面是多个 Telegram bot，
后续支持 FoundryVTT。设计论证见 [spec_claude_20260707.md](spec_claude_20260707.md)，
落地计划见 `~/.claude/plans/transient-discovering-wilkinson.md`。

当前进度：**M0 —— 引擎骨架**（Model Gateway / 分层 Prompt Builder / 单角色单调用多气泡 +
记忆增量 / 单元测试 + 离线回放）。

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

## 代码结构（`src/aichatgroup/`）

| 子包 / 模块 | 职责 |
| --- | --- |
| `domain/` | 领域层：`types.py`（`WorldBook`/`Agent`/`RoomState`/`TurnResult`/`PacingConfig` ...）+ `markers.py`（控制标记词表） |
| `gateway/` | Model Gateway：`base.py`（协议+辅助）、`anthropic_gateway.py`、`mock.py`（模拟前缀缓存） |
| `prompt/` | `builder.py`：分层 Prompt 组装 + 显式 `cache_control` 断点 |
| `engine/` | 运行层：`parsing.py`（多气泡+记忆增量）、`pacing.py`（气泡节奏）、`turn.py`（发言回合执行器） |
| `config.py` / `logging_setup.py` | 跨层基础设施：配置与日志 |

常用符号在顶层再导出：`from aichatgroup import Agent, run_turn, MockGateway, build_prompt`。

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

## 输出契约

被点名的角色一次调用输出 1~3 条气泡，相邻两条之间用 `<<SEPARATOR>>` 分隔；可选在末尾追加
`<<MEMORY>>` + 一段 JSON 作为记忆增量，引擎在外部合并进该角色的私有快照。控制标记词表集中在
[markers.py](src/aichatgroup/domain/markers.py)，解析对大小写/空白容忍；后续将由预设配置驱动。

> **Prompt 结构方向**：PromptBuilder 会逐步向 SillyTavern 预设结构靠拢（命名 prompt 片段 +
> 顺序/开关 + marker 占位 + 深度注入，见 `preset/example.json`），并支持导入 SillyTavern 预设
> 来控制模型行为——预设不替代 Builder，只提供结构与文案。当前四层组装是该模型的一个特例。

## 气泡节奏（与性格接驳）

气泡之间的停顿由 [pacing.py](src/aichatgroup/engine/pacing.py) 推断，结果放在 `TurnResult.pauses`，
供 M1 的 Telegram 发送层（typing 提示 + sleep）消费。两条来源：

- **模型显式**：分隔符可带秒数 `<<SEPARATOR:2>>`；
- **缺省推断**：无显式值时按下一条气泡长度估算。

**原则**：一切涉及推断的行为都要留有与角色性格接驳的口子——把可调 factor 存进**角色设定**。
停顿是第一个落点：每个 `Agent` 带一个 `PacingConfig`（`per_char_s` / `explicit_scale` 等），
急性子停得短、慢性子停得长。后续新增的推断行为应循同一模式挂到角色上。

## 路线图

- **M1（MVP）** Telegram 多 bot 热闹群聊：Telegram Adapter、Director 调度器、
  手写世界书/角色卡、开关键、SQLite 持久化、基础 compaction。
- **M2** Storyteller（编导/压力源）+ 更强记忆。
- **M3** 知识隔离。 **M4** 世界书生成 + RAG。 **M5** FoundryVTT 支持。
