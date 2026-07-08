"""集中管理「引擎元指令」的 prompt 文本（A 类）。

把 usher / director / compaction 的 system 指令，以及角色面「输出契约」的**纯文本**从代码里
搬到这里，每个一份 `.md`——便于手动修改、且彻底免去 f-string 里的转义（`{{{{…}}}}`、`\"`）。

**区分**（易混）：本包 `prompts/`（复数）= 原始 prompt **文本资产**；`message/prompt/`（单数）=
角色面分层 **组装逻辑**（builder）。文本进这里，组装/解析逻辑留在各自模块。

**整段 prompt 都在文件里**：system 与 user 都成模板（`<name>.system.md` / `<name>.user.md`），
要填的运行时数据用 `$slot` 占位（`string.Template`），代码只算数据、`render()` 回填。用 `$` 而非
`{}`：这样 prompt 里字面的 `{{SEPARATOR}}`（marker）、`{"notes": …}`（JSON 示例）**无需任何转义**。
（若真需要字面 `$`，写 `$$`。）

**契约边界**：marker 词表、usher 的 `DIRECTIONS`、director 的 `none`、MockGateway 认角色用的
「扮演的角色是「…」」这类**机器要读的契约**仍是代码常量/正则、留在原处；这里只放给模型看的散文。
`tests/test_prompts.py` 断言契约词确实出现在对应 prompt 里，防散文与代码漂移。

打包提示：`.md` 与本文件同目录，靠 `__file__` 定位（源码运行即可）。若将来打 wheel，记得把
`aichatgroup/prompts/*.md` 纳入 package data。
"""
from __future__ import annotations

from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


def load(name: str) -> str:
    """读取 `prompts/<name>.md` 的纯文本（首尾空白剥掉）。"""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name, /, **subs: object) -> str:
    """load 后用 `$slot` 回填运行时数据（`safe_substitute`：缺 slot 原样留、不炸）。

    name 是位置参数（`/`），故 slot 可以叫 `$name` 而不与它撞。
    """
    return Template(load(name)).safe_substitute(subs)
