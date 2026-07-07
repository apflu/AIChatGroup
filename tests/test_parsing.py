"""输出解析：气泡切分、停顿、动作/语言 parts、记忆增量、自名剥离、容错。

parse_turn_output(text, speaker) -> (bubbles: list[ParsedBubble], memory_delta)。
断言多用 ParsedBubble 的便利属性：`.text`(仅语言) / `.display`(动作+语言渲染) / `.parts` / `.pause_hint`。
"""
from aichatgroup.engine import parse_turn_output


def texts(bubbles):
    return [b.text for b in bubbles]


def displays(bubbles):
    return [b.display for b in bubbles]


def hints(bubbles):
    return [b.pause_hint for b in bubbles]


# ---- 气泡切分 / 停顿 ---------------------------------------------------
def test_single_bubble_no_memory():
    bubbles, mem = parse_turn_output("你好呀")
    assert texts(bubbles) == ["你好呀"]
    assert hints(bubbles) == [None]
    assert mem is None


def test_multi_bubble_split():
    bubbles, mem = parse_turn_output("收到！{{SEPARATOR}}我看看{{SEPARATOR}}等下，这里有个问题")
    assert texts(bubbles) == ["收到！", "我看看", "等下，这里有个问题"]
    assert hints(bubbles) == [None, None, None]
    assert mem is None


def test_bubbles_clamped_to_three():
    bubbles, _ = parse_turn_output("a{{SEPARATOR}}b{{SEPARATOR}}c{{SEPARATOR}}d{{SEPARATOR}}e")
    assert texts(bubbles) == ["a", "b", "c"]


def test_separator_is_tolerant():
    bubbles, _ = parse_turn_output("甲{{ separator }}乙{{Separator}}丙")
    assert texts(bubbles) == ["甲", "乙", "丙"]


def test_explicit_pause_hints():
    bubbles, _ = parse_turn_output("先说这句{{SEPARATOR:2}}停两秒再说{{SEPARATOR:0.5}}紧接着")
    assert texts(bubbles) == ["先说这句", "停两秒再说", "紧接着"]
    assert hints(bubbles) == [None, 2.0, 0.5]


def test_explicit_pause_with_spaces():
    bubbles, _ = parse_turn_output("a{{SEPARATOR : 1.5}}b")
    assert texts(bubbles) == ["a", "b"]
    assert hints(bubbles) == [None, 1.5]


# ---- 动作 / 语言 parts -------------------------------------------------
def test_asterisk_action_split():
    bubbles, _ = parse_turn_output("*抱起琴* 大哥别急着走呀~")
    (b,) = bubbles
    assert [(p.kind, p.text) for p in b.parts] == [
        ("action", "抱起琴"), ("speech", "大哥别急着走呀~")
    ]
    assert b.text == "大哥别急着走呀~"            # 仅语言
    assert b.display == "（抱起琴）大哥别急着走呀~"  # 动作+语言渲染


def test_marker_action_split():
    bubbles, _ = parse_turn_output("{{ACTION}}抱起琴{{/ACTION}}你好")
    (b,) = bubbles
    assert [(p.kind, p.text) for p in b.parts] == [("action", "抱起琴"), ("speech", "你好")]


def test_action_only_bubble():
    bubbles, _ = parse_turn_output("*叹了口气*")
    (b,) = bubbles
    assert [p.kind for p in b.parts] == ["action"]
    assert b.text == ""                    # 无语言
    assert b.display == "（叹了口气）"


def test_action_in_middle():
    bubbles, _ = parse_turn_output("我请客*提裙子*了")
    (b,) = bubbles
    assert [(p.kind, p.text) for p in b.parts] == [
        ("speech", "我请客"), ("action", "提裙子"), ("speech", "了")
    ]
    assert b.display == "我请客（提裙子）了"


def test_pure_speech_display_equals_text():
    # 纯语言时 display == text，保证历史渲染与旧格式逐字节一致（缓存不变式）
    bubbles, _ = parse_turn_output("就是一句普通台词")
    (b,) = bubbles
    assert b.display == b.text == "就是一句普通台词"


# ---- 记忆增量 ----------------------------------------------------------
def test_memory_extraction():
    bubbles, mem = parse_turn_output('好的。\n{{MEMORY}}{"notes": "用户想要热闹的地方"}')
    assert texts(bubbles) == ["好的。"]
    assert mem == {"notes": "用户想要热闹的地方"}


def test_memory_with_code_fence():
    bubbles, mem = parse_turn_output('嗯。\n{{MEMORY}}```json\n{"mood": "警惕"}\n```')
    assert texts(bubbles) == ["嗯。"]
    assert mem == {"mood": "警惕"}


def test_memory_with_closing_tag():
    bubbles, mem = parse_turn_output('好的。\n{{MEMORY}}{"notes": "初次登场"}\n{{/MEMORY}}')
    assert texts(bubbles) == ["好的。"]
    assert mem == {"notes": "初次登场"}


def test_memory_with_legacy_angle_closing():
    _, mem = parse_turn_output('嗯。\n{{MEMORY}}{"mood": "警惕"}</MEMORY>')
    assert mem == {"mood": "警惕"}


def test_memory_with_trailing_junk_brace_fallback():
    _, mem = parse_turn_output('在。\n{{MEMORY}}{"k": 1} 就这些啦')
    assert mem == {"k": 1}


def test_bad_memory_is_ignored():
    bubbles, mem = parse_turn_output("在的。\n{{MEMORY}}not-json")
    assert texts(bubbles) == ["在的。"]
    assert mem is None


# ---- 自名前缀剥离 ------------------------------------------------------
def test_strip_self_speaker_tag():
    bubbles, _ = parse_turn_output("[小诗] 哎呀你好呀{{SEPARATOR}}[小诗]在呢", speaker="小诗")
    assert texts(bubbles) == ["哎呀你好呀", "在呢"]


def test_strip_self_tag_colon_forms():
    assert texts(parse_turn_output("[小诗]：你好", speaker="小诗")[0]) == ["你好"]
    assert texts(parse_turn_output("小诗：你好", speaker="小诗")[0]) == ["你好"]
    assert texts(parse_turn_output("小诗:hi", speaker="小诗")[0]) == ["hi"]


def test_self_tag_not_stripped_without_speaker():
    assert texts(parse_turn_output("[小诗] 你好")[0]) == ["[小诗] 你好"]


def test_other_bracket_tags_are_kept():
    bubbles, _ = parse_turn_output("[叹气] 累了", speaker="小诗")
    assert texts(bubbles) == ["[叹气] 累了"]


def test_bubble_that_is_only_self_tag_is_dropped():
    bubbles, _ = parse_turn_output("[小诗]{{SEPARATOR}}真的来了", speaker="小诗")
    assert texts(bubbles) == ["真的来了"]


def test_dashes_are_no_longer_separators():
    bubbles, _ = parse_turn_output("这是 --- 一段话\n第二行还有 ---")
    assert texts(bubbles) == ["这是 --- 一段话\n第二行还有 ---"]


# ---- fuzz / property：乱序穿插标记不崩、语义稳定 ----------------------
def test_fuzz_marker_soup_never_crashes():
    import random

    tokens = [
        "{{SEPARATOR}}", "{{SEPARATOR:2}}", "{{MEMORY}}", "{{/MEMORY}}",
        "*动作*", "{{ACTION}}x{{/ACTION}}", "[小诗]", "小诗：", "台词",
        '{"a":1}', "```json", "```", "</MEMORY>", "\n", "甲乙丙",
    ]
    rng = random.Random(20260707)
    for _ in range(400):
        text = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 12)))
        bubbles, mem = parse_turn_output(text, speaker="小诗")
        # 不变式：不崩；气泡数有界；每条至少有一个 part；mem 要么 None 要么 dict
        assert len(bubbles) <= 3
        assert all(b.parts for b in bubbles)
        assert mem is None or isinstance(mem, dict)
        # 标记不应泄进最终 display
        for b in bubbles:
            assert "{{SEPARATOR" not in b.display and "{{MEMORY" not in b.display
