"""引擎的 prompt 文本资产（A 类）——给模型看的散文全在这里的 `.md` 里，代码只算数据。

目录按「模型看到的一段」组织，而非按缓存层：

    role/         角色面（每个发言 agent 收到的分层 prompt）
      world.md            第 0 层：世界观圣经 + 群聊规则（独立缓存块）
      situation.md        第 1 层：前情提要 + 关系图谱 + 在场玩家（独立缓存块）
      tail.md             第 3 层尾部：人设 + 独知 + 记忆 + 编导指令，末尾 include 输出契约
      output_contract.md  角色输出格式（气泡 / 动作 / 回复 / 记忆 marker 的教法）
    usher/  conductor/  storyteller/  compaction/
      system.md  user.md  四个便宜模型各自的 system 指令与 user 模板

**模板语法**：jinja2，但变量定界符改成 `${slot}`，块保持 `{% if %} … {% endif %}` / `{% for %}`，
注释是 `<# … #>`。这样 prompt 里字面的 `{{SEPARATOR}}`（marker）、`{"notes": …}`（JSON 示例）
**无需任何转义**——这正是不用 `{{ }}` 的原因。兜底文案（"（还没有人说话）"之类）写在模板的
`{% else %}` 里，不在 Python 里。渲染后连续空行折叠成一个，所以块标签行随便留空。

**区分**（易混）：本包 `prompts/`（复数）= 文本资产；`message/prompt/`（单数）= 角色面分层
**组装逻辑**（builder、缓存断点）。文本进这里，组装/解析逻辑留在各自模块。

**契约边界**：marker 词表、usher 的 `DIRECTIONS`、conductor 的 `none`、storyteller 的 `KIND:/HOOK:/KNOW`、
MockGateway 认角色用的「扮演的角色是「…」」这类**机器要读的契约**仍是代码常量/正则，留在解析器身边；
这里只放给模型看的散文。`tests/test_prompts.py` 断言契约词确实出现在对应 prompt 里，防散文与代码漂移；
`tests/test_prompt_golden.py` 快照模型实际收到的全文，改任何一个 `.md` 都会以 diff 形式显示出来。

**覆盖**：`set_override_dir(path)` 指定一个目录，同名相对路径的 `.md` 优先于包内的（预设的
`prompts_dir` 走这里）——私有世界的散文可以跟着预设走，不必改包。

打包：`.md` 是 package data（pyproject `prompts/*/*.md`），靠 `__file__` 定位。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

_DIR = Path(__file__).parent
_override_dir: Path | None = None
_BLANK_RUN = re.compile(r"\n{3,}")


def set_override_dir(path: str | Path | None) -> None:
    """设置（或清除）覆盖目录；之后的 load/render 先查它。"""
    global _override_dir
    _override_dir = Path(path) if path else None
    _env.cache_clear()


def override_dir() -> Path | None:
    return _override_dir


@lru_cache(maxsize=1)
def _env() -> Environment:
    loaders = [FileSystemLoader(str(_DIR), encoding="utf-8")]
    if _override_dir is not None:
        loaders.insert(0, FileSystemLoader(str(_override_dir), encoding="utf-8"))
    return Environment(
        loader=ChoiceLoader(loaders),
        variable_start_string="${",
        variable_end_string="}",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,
        undefined=StrictUndefined,
    )


def _tidy(text: str) -> str:
    return _BLANK_RUN.sub("\n\n", text).strip()


def load(name: str) -> str:
    """读 `prompts/<name>.md` 的**模板源文本**（首尾空白剥掉；覆盖目录优先）。
    没有 slot 的纯指令（各 `system.md`）直接用它；有 slot 的用 `render`。"""
    source, _, _ = _env().loader.get_source(_env(), f"{name}.md")
    return source.strip()


def render(name: str, /, **ctx: object) -> str:
    """渲染 `prompts/<name>.md`。缺 slot 直接报错（StrictUndefined），别让 `${x}` 漏给模型。"""
    return _tidy(_env().get_template(f"{name}.md").render(**ctx))
