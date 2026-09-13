# 世界局势
{% if summary or relations %}
{% if summary %}${summary}
{% endif %}
{% if relations %}关系：${relations}
{% endif %}
{% else %}
（暂无既有局势）
{% endif %}

# 在场角色
{% if agents %}{% for a in agents %}${a.name}(${a.id}){% if not loop.last %}、{% endif %}{% endfor %}{% else %}（未提供在场角色）{% endif %}

# 最近对话
{% if recent %}${recent}{% else %}（还没有人说话）{% endif %}

# 上一段是怎么结束的
{% if last_end %}
原因：${last_end.reason}
概述：{% if last_end.summary_hook %}${last_end.summary_hook}{% else %}（无）{% endif %}

用户方向标签（仅 user_forced 时有意义）：{% if last_end.direction %}${last_end.direction}{% else %}（无）{% endif %}

{% else %}
（这是第一段会话）
{% endif %}

请为下一段对话定意图。输出 KIND 和 HOOK 两行；如有知情差再加 KNOW 行：
