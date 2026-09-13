"""集中 prompt 资产 + 契约漂移守卫。

整段 prompt 都在 prompts/<段>/*.md（jinja2，变量 `${slot}`），机器契约（marker 值 / DIRECTIONS /
none / MockGateway 认角色的短语）是代码常量。这里断言每个契约词确实出现在对应散文里——散文改跑偏、
或常量改了忘同步散文，都会红。全文快照见 test_prompt_golden.py。
"""
from aichatgroup.domain.markers import BUBBLE_SEPARATOR, MEMORY_MARKER
from aichatgroup.message.usher import DIRECTIONS
from aichatgroup.prompts import load, render

_ALL = [
    "usher/system", "usher/user",
    "conductor/system", "conductor/user",
    "storyteller/system", "storyteller/user",
    "compaction/system", "compaction/user",
    "role/world", "role/situation", "role/tail", "role/output_contract",
]


def test_all_prompts_load_nonempty():
    for name in _ALL:
        assert load(name).strip(), f"{name}.md 为空"


def test_usher_prompt_lists_every_direction_and_absorb():
    text = load("usher/system")
    for word in DIRECTIONS:
        assert word in text, f"usher.system.md 缺方向词 {word!r}（与 DIRECTIONS 漂移）"
    assert "absorb" in text


def test_usher_prompt_carries_violate_marker():
    # violate 是 canon 违规的机器契约（parser 据此置 violation）；散文必须描述它
    from aichatgroup.message.usher import VIOLATE_MARKER
    assert VIOLATE_MARKER in load("usher/system"), "usher.system.md 缺 violate 标记（与解析器漂移）"


def test_storyteller_prompt_carries_know_contract():
    # KNOW 是 ModelStoryteller._parse 的授知机器契约；散文须描述它，防漂移
    from aichatgroup.story.storyteller.model import _KNOW_LABEL
    assert _KNOW_LABEL in load("storyteller/system")


def test_storyteller_user_fills_cast_and_fallbacks():
    from aichatgroup.domain import Agent
    agents = [Agent(id="a2", name="阿福", model_id="m")]
    out = render("storyteller/user", summary="", relations="", agents=agents, recent="", last_end=None)
    assert "阿福" in out and "a2" in out
    assert "（暂无既有局势）" in out and "（还没有人说话）" in out and "（这是第一段会话）" in out
    assert "$" not in out          # 所有 slot 都被填


def test_conductor_prompt_mentions_none_contract():
    assert "none" in load("conductor/system")


def test_storyteller_prompt_carries_output_contract_labels():
    # KIND:/HOOK: 是 ModelStoryteller._parse 的机器契约；kind 词表也须在散文里
    from aichatgroup.domain.conversation import INTENT_KINDS
    text = load("storyteller/system")
    assert "KIND:" in text and "HOOK:" in text
    for kind in INTENT_KINDS:
        assert kind in text, f"storyteller.system.md 缺意图种类 {kind!r}"


def test_output_contract_carries_actual_marker_values():
    text = load("role/output_contract")
    # 断言 marker 的**实际值**在散文里——markers.py 改了这里必须同步
    assert BUBBLE_SEPARATOR in text, f"output_contract.md 缺 {BUBBLE_SEPARATOR}"
    assert MEMORY_MARKER in text, f"output_contract.md 缺 {MEMORY_MARKER}"


def test_tail_carries_mockgateway_contract_phrase():
    # MockGateway 用正则 `扮演的角色是「(.+?)」` 从 tail 认出当前角色；短语丢了它就瞎
    assert "扮演的角色是「" in load("role/tail")
    out = render("role/tail", base_prompt="", name="小丸子", character_card="", knowledge="", memory="", conductor="")
    assert "你现在扮演的角色是「小丸子」。" in out
    assert "{{MEMORY}}" in out      # 尾部 include 了输出契约


def test_user_templates_fill_slots_and_leave_no_placeholder():
    out = render("usher/user", recent="R1", speaker="老陈", text="我掏出手机")
    for v in ("R1", "老陈", "我掏出手机"):
        assert v in out
    assert "$" not in out  # 所有 slot 都被填了


def test_missing_slot_is_an_error_not_a_leak():
    import pytest
    from jinja2.exceptions import UndefinedError
    with pytest.raises(UndefinedError):
        render("usher/user", recent="R1")   # 少了 speaker/text → 报错，而不是把 ${text} 漏给模型


def test_render_leaves_literal_braces_untouched():
    # `$` 回填不该碰字面 `{{…}}`(marker) 或 `{…}`(JSON) —— 这正是不用 str.format 的原因
    out = render("role/output_contract")  # 无 slot，等价 load，但确认模板引擎不碰 {{ }} / { }
    assert BUBBLE_SEPARATOR in out and '{"notes"' in out


def test_no_fstring_escaping_leaked_into_assets():
    text = load("role/output_contract")
    assert "{{{{" not in text
    assert '\\"' not in text
