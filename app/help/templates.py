import re
from typing import Any, Dict, Optional

from app.knowledge.help.loader import help_knowledge

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_NOT_READY_MARKERS = ("TODO", "MISSING_FROM_DOCUMENT")

_FALLBACK_TEXT = (
    "Xin lỗi bạn, mình chưa thể hiển thị đầy đủ thông tin lúc này. "
    "Bạn vui lòng thử lại hoặc liên hệ CSKH giúp mình nhé!"
)


def is_template_ready(template: Dict[str, Any]) -> bool:
    content = template.get("content", "")
    return not any(marker in content for marker in _NOT_READY_MARKERS)


def render_template(template_id: str, context: Dict[str, Any]) -> Optional[str]:
    """Renders response_template.json's `content` with {{placeholder}}
    substitution from `context`. Returns None when the template is missing,
    isn't ready yet (still a TODO/MISSING_FROM_DOCUMENT placeholder), or a
    required variable wasn't supplied (leftover "{{" after substitution) -
    the safety guard from the approved plan §4 step 6: never show placeholder
    text or raw moustache syntax to a real user. Callers must fall back to
    render_or_fallback() / escalate when this returns None."""
    template = help_knowledge.get_template(template_id)
    if not template or not is_template_ready(template):
        return None

    def _sub(match: "re.Match[str]") -> str:
        value = context.get(match.group(1))
        return str(value) if value is not None else match.group(0)

    rendered = _PLACEHOLDER_RE.sub(_sub, template["content"])
    if "{{" in rendered:
        return None
    return rendered


def render_or_fallback(template_id: str, context: Dict[str, Any]) -> str:
    """render_template() with the generic-fallback safety net always
    applied - this is the function business_object_executor.py/orchestrator.py actually calls."""
    rendered = render_template(template_id, context)
    if rendered is not None:
        return rendered
    fallback = render_template("RT_RENDER_FALLBACK_GENERIC", context)
    return fallback if fallback is not None else _FALLBACK_TEXT
