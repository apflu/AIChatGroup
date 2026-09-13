# 在场角色（只能从这些 id 里选）
{% for a in agents %}
- ${a.id}：${a.name}
{% endfor %}

# 最近对话
{% if recent %}${recent}{% else %}（还没有人说话）{% endif %}

请输出下一个开口的角色 id（${ agents | map(attribute="id") | join("、") }{% if allow_silence %}，或 none{% endif %}）：
