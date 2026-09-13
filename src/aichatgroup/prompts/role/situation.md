{% if summary %}
# 前情提要
${summary}

{% endif %}
{% if relations %}
# 客观关系图谱
${relations}

{% endif %}
{% if players %}
# 在场的人类玩家
{% for name, persona in players.items() %}
- ${name}{% if persona %}：${persona}{% endif %}

{% endfor %}

{% endif %}
{% if not summary and not relations and not players %}
（暂无前情提要）
{% endif %}
