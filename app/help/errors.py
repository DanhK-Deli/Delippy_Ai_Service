from enum import Enum
from typing import Any, Dict, Tuple

import httpx

from app.client.delippy_client import DelippyRateLimitedError
from app.knowledge.help.loader import help_knowledge


class MissingAuthError(Exception):
    """Raised BEFORE any network call - never actually sent to the backend.
    Per .agents/AGENTS.md rule 3: a Guest (no token) attempting a Protected
    Action must not reach the backend API at all; business_object_executor.py's
    _run_tool() raises this the moment it sees tool.json's required_auth=true
    with no token supplied, instead of making the call and waiting for a
    real 401."""


class ErrorGroup(str, Enum):
    """Mirrors error_message.json's error_group values exactly - one enum
    member per registered group, so a typo in a group name is a Python
    NameError, not a silently-unmatched string."""

    UNAUTHENTICATED = "unauthenticated"
    AUTH_ERROR_SENSITIVE = "auth_error_sensitive"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    CRITICAL_SYSTEM_ERROR = "critical_system_error"
    TIMEOUT = "timeout"
    UNKNOWN_OR_NEW = "unknown_or_new"


def classify_exception(exc: Exception, *, token_was_supplied: bool) -> ErrorGroup:
    """Classifies any exception raised by a tool call (see app/help/tools.py)
    into exactly one error_message.json group - see the approved plan §5.
    token_was_supplied is what distinguishes a genuine "not logged in yet"
    401 (UNAUTHENTICATED - ask for identity, no ticket) from a real security
    anomaly (AUTH_ERROR_SENSITIVE - escalate immediately)."""
    if isinstance(exc, MissingAuthError):
        # Detected pre-call (no token, tool.json required_auth=true) - by
        # construction this is always the Guest/no-token case, never the
        # security-anomaly one.
        return ErrorGroup.UNAUTHENTICATED
    if isinstance(exc, DelippyRateLimitedError):
        return ErrorGroup.RATE_LIMITED
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return ErrorGroup.AUTH_ERROR_SENSITIVE if token_was_supplied else ErrorGroup.UNAUTHENTICATED
        if status == 404:
            return ErrorGroup.NOT_FOUND
        if status == 429:
            return ErrorGroup.RATE_LIMITED
        if status >= 500:
            return ErrorGroup.CRITICAL_SYSTEM_ERROR
        return ErrorGroup.UNKNOWN_OR_NEW
    if isinstance(exc, httpx.RequestError):
        return ErrorGroup.TIMEOUT
    return ErrorGroup.UNKNOWN_OR_NEW


def error_mapping_for(group: ErrorGroup) -> Dict[str, Any]:
    """The matching entry from error_message.json's error_mappings. Falls
    back to a safe generic shape if somehow not registered (defensive only -
    every ErrorGroup member has a real entry as of this build)."""
    mappings = (help_knowledge.error_message or {}).get("error_mappings", [])
    for m in mappings:
        if m.get("error_group") == group.value:
            return m
    return {
        "error_group": group.value,
        "response_template": "RT_ERROR_GENERIC_FALLBACK",
        "escalate_immediately": False,
    }


def handle_exception(exc: Exception, *, token_was_supplied: bool) -> Tuple[ErrorGroup, str, bool]:
    """Single entry point business_object_executor.py calls for any tool-call exception.
    Returns (group, response_template_id, escalate_immediately)."""
    group = classify_exception(exc, token_was_supplied=token_was_supplied)
    mapping = error_mapping_for(group)
    return group, mapping.get("response_template", "RT_ERROR_GENERIC_FALLBACK"), bool(mapping.get("escalate_immediately"))
