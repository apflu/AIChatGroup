"""集中 prompt 资产 + 契约漂移守卫。

整段 prompt（system + user 模板 + 尾部片段 + 人设）都在 prompts/*.md，运行时数据用 `$slot` 回填；
机器契约（marker 值 / DIRECTIONS / none / MockGateway 认角色的短语）是代码常量。
这里断言每个契约词确实出现在对应散文里——散文改跑偏、或常量改了忘同步散文，都会红。
"""
from aichatgroup.domain.markers import BUBBLE_SEPARATOR, MEMORY_MARKER
from aichatgroup.message.usher import DIRECTIONS
from aichatgroup.prompts import load, render

_ALL = [
    "usher.system", "usher.user",
    "conductor.system", "conductor.user",
    "storyteller.system", "storyteller.user",
    "compaction.system", "compaction.user",
    "output_contract", "tail_header", "tail_memory", "tail_conductor", "persona",
    "world", "layer1_summary", "layer1_relations",
]


def test_all_prompts_load_nonempty():
    for name in _ALL:
        assert load(name).strip(), f"{name}.md 为空"


def test_usher_prompt_lists_every_direction_and_absorb():
    text = load("usher.system")
    for word in DIRECTIONS:
        assert word in text, f"usher.system.md 缺方向词 {word!r}（与 DIRECTIONS 漂移）"
    assert "absorb" in text


def test_conductor_prompt_mentions_none_contract():
    assert "none" in load("conductor.system")


def test_storyteller_prompt_carries_output_contract_labels():
    # KIND:/HOOK: 是 ModelStoryteller._parse 的机器契约；kind 词表也须在散文里
    from aichatgroup.domain.conversation import INTENT_KINDS
    text = load("storyteller.system")
    assert "KIND:" in text and "HOOK:" in text
    for kind in INTENT_KINDS:
        assert kind in text, f"storyteller.system.md 缺意图种类 {kind!r}"


def test_output_contract_carries_actual_marker_values():
    text = load("output_contract")
    # 断言 marker 的**实际值**在散文里——markers.py 改了这里必须同步
    assert BUBBLE_SEPARATOR in text, f"output_contract.md 缺 {BUBBLE_SEPARATOR}"
    assert MEMORY_MARKER in text, f"output_contract.md 缺 {MEMORY_MARKER}"


def test_persona_carries_mockgateway_contract_phrase():
    # MockGateway 用正则 `扮演的角色是「(.+?)」` 从 tail 认出当前角色；短语丢了它就瞎
    assert "扮演的角色是「" in load("persona")
    assert render("persona", name="小丸子") == "你现在扮演的角色是「小丸子」。"


def test_user_templates_fill_slots_and_leave_no_placeholder():
    out = render("usher.user", recent="R1", speaker="老陈", text="我掏出手机")
    for v in ("R1", "老陈", "我掏出手机"):
        assert v in out
    assert "$" not in out  # 所有 slot 都被填了


def test_render_leaves_literal_braces_untouched():
    # `$` 回填不该碰字面 `{{…}}`(marker) 或 `{…}`(JSON) —— 这正是不用 str.format 的原因
    out = render("output_contract")  # 无 slot，等价 load，但确认 Template 不炸
    assert BUBBLE_SEPARATOR in out and '{"notes"' in out


def test_no_fstring_escaping_leaked_into_assets():
    text = load("output_contract")
    assert "{{{{" not in text
    assert '\\"' not in text
