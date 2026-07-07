from aichatgroup.engine import parse_turn_output


def test_single_bubble_no_memory():
    bubbles, hints, mem = parse_turn_output("你好呀")
    assert bubbles == ["你好呀"]
    assert hints == [None]
    assert mem is None


def test_multi_bubble_split():
    text = "收到！{{SEPARATOR}}我看看{{SEPARATOR}}等下，这里有个问题"
    bubbles, hints, mem = parse_turn_output(text)
    assert bubbles == ["收到！", "我看看", "等下，这里有个问题"]
    assert hints == [None, None, None]
    assert mem is None


def test_bubbles_clamped_to_three():
    text = "a{{SEPARATOR}}b{{SEPARATOR}}c{{SEPARATOR}}d{{SEPARATOR}}e"
    bubbles, hints, _ = parse_turn_output(text)
    assert bubbles == ["a", "b", "c"]
    assert len(hints) == 3


def test_separator_is_tolerant():
    text = "甲{{ separator }}乙{{Separator}}丙"
    bubbles, _, _ = parse_turn_output(text)
    assert bubbles == ["甲", "乙", "丙"]


def test_explicit_pause_hints():
    text = "先说这句{{SEPARATOR:2}}停两秒再说{{SEPARATOR:0.5}}紧接着"
    bubbles, hints, _ = parse_turn_output(text)
    assert bubbles == ["先说这句", "停两秒再说", "紧接着"]
    assert hints == [None, 2.0, 0.5]


def test_explicit_pause_with_spaces():
    text = "a{{SEPARATOR : 1.5}}b"
    bubbles, hints, _ = parse_turn_output(text)
    assert bubbles == ["a", "b"]
    assert hints == [None, 1.5]


def test_memory_extraction():
    text = '好的。\n{{MEMORY}}{"notes": "用户想要热闹的地方"}'
    bubbles, hints, mem = parse_turn_output(text)
    assert bubbles == ["好的。"]
    assert hints == [None]
    assert mem == {"notes": "用户想要热闹的地方"}


def test_memory_with_code_fence():
    text = '嗯。\n{{MEMORY}}```json\n{"mood": "警惕"}\n```'
    bubbles, _, mem = parse_turn_output(text)
    assert bubbles == ["嗯。"]
    assert mem == {"mood": "警惕"}


def test_memory_with_closing_tag():
    # 模型把 {{MEMORY}} 当标签，补了个 {{/MEMORY}} 闭合
    text = '好的。\n{{MEMORY}}{"notes": "初次登场"}\n{{/MEMORY}}'
    bubbles, _, mem = parse_turn_output(text)
    assert bubbles == ["好的。"]
    assert mem == {"notes": "初次登场"}


def test_memory_with_legacy_angle_closing():
    # 兼容：模型若仍补旧式 </MEMORY>，也照样剥掉（实机见过）
    text = '嗯。\n{{MEMORY}}{"mood": "警惕"}</MEMORY>'
    _, _, mem = parse_turn_output(text)
    assert mem == {"mood": "警惕"}


def test_memory_with_trailing_junk_brace_fallback():
    text = '在。\n{{MEMORY}}{"k": 1} 就这些啦'
    _, _, mem = parse_turn_output(text)
    assert mem == {"k": 1}


def test_bad_memory_is_ignored():
    text = "在的。\n{{MEMORY}}not-json"
    bubbles, _, mem = parse_turn_output(text)
    assert bubbles == ["在的。"]
    assert mem is None


def test_strip_self_speaker_tag():
    # 模型模仿历史 [发言者] 格式给自己台词加前缀，应剥掉
    text = "[小诗] 哎呀你好呀{{SEPARATOR}}[小诗]在呢"
    bubbles, _, _ = parse_turn_output(text, speaker="小诗")
    assert bubbles == ["哎呀你好呀", "在呢"]


def test_strip_self_tag_colon_forms():
    assert parse_turn_output("[小诗]：你好", speaker="小诗")[0] == ["你好"]
    assert parse_turn_output("小诗：你好", speaker="小诗")[0] == ["你好"]
    assert parse_turn_output("小诗:hi", speaker="小诗")[0] == ["hi"]


def test_self_tag_not_stripped_without_speaker():
    # 不传 speaker → 保持原样（向后兼容）
    assert parse_turn_output("[小诗] 你好")[0] == ["[小诗] 你好"]


def test_other_bracket_tags_are_kept():
    # 名字不匹配的方括号（如舞台提示）不该被剥
    bubbles, _, _ = parse_turn_output("[叹气] 累了", speaker="小诗")
    assert bubbles == ["[叹气] 累了"]


def test_bubble_that_is_only_self_tag_is_dropped():
    text = "[小诗]{{SEPARATOR}}真的来了"
    bubbles, _, _ = parse_turn_output(text, speaker="小诗")
    assert bubbles == ["真的来了"]


def test_dashes_are_no_longer_separators():
    text = "这是 --- 一段话\n第二行还有 ---"
    bubbles, _, _ = parse_turn_output(text)
    assert bubbles == ["这是 --- 一段话\n第二行还有 ---"]
