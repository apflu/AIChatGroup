"""控制标记词表（control-marker vocabulary）。

模型在一次发言回合的输出里用这些 `{{...}}` 标记来结构化内容：
- BUBBLE_SEPARATOR: 分隔连发的多条气泡
- MEMORY_MARKER:    其后跟一段 JSON，作为记忆增量

为什么用 `{{...}}` 而非 `<<...>>`：尖括号会诱发模型的「XML 要闭合」本能，实机里模型
会给 `<<MEMORY>>` 补一个 `</MEMORY>` 把 JSON 尾部弄脏。双花括号是「模板占位符」语感，
几乎不在自然对话里出现、也不诱发闭合；且与 SillyTavern 宏（`{{char}}`/`{{user}}`）一致，
利于后续对齐 ST 预设结构。

集中在此定义,是为了两件事:
1. 统一标记风格(都走 `{{...}}`),便于教模型、便于解析;
2. **为后续对齐 SillyTavern 预设留口子** —— 未来 PromptBuilder 会走向
   「命名 prompt 片段 + 顺序/开关 + marker 占位 + 深度注入」的结构(见
   preset/example.json 的 prompts / prompt_order),届时这些分隔/标记约定
   应当由预设配置驱动、而非硬编码。现在先集中成常量,改起来只动一处。

解析侧对大小写与内部空白保持容忍(见 engine/parsing.py),所以 `{{separator}}`、
`{{ SEPARATOR }}` 等变体都能被识别；模型误补的闭合标记 `{{/MEMORY}}` 也会被剥掉。
"""
from __future__ import annotations

BUBBLE_SEPARATOR = "{{SEPARATOR}}"
MEMORY_MARKER = "{{MEMORY}}"

# 分隔符可携带显式停顿秒数：`{{SEPARATOR:2}}` / `{{SEPARATOR:1.5}}`。
# 省略数字则由 pacing 按下一条气泡长度推断（见 engine/pacing.py）。

# 动作/语言分离：动作可用 `{{ACTION}}…{{/ACTION}}` 包裹，也容忍 RP 惯用的 `*…*`；
# 其余为语言。解析统一归到 ContentPart(kind=action|speech)（见 engine/parsing.py）。
ACTION_OPEN = "{{ACTION}}"
ACTION_CLOSE = "{{/ACTION}}"

# 回复寻址：模型在一条气泡开头写 `{{REPLY:37}}` 表示回复历史里 ⟦37⟧ 那条。
# 引擎剥掉标记、把内部 id 存进该气泡的 reply_to（见 engine/parsing.py）。
REPLY_MARKER = "{{REPLY}}"
