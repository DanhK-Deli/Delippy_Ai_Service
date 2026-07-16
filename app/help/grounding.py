import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.help.fact_manifest import Fact

# 2+ digit runs only - a bare single digit is almost always a bullet/ordinal
# ("bước 1", "lần 2") rather than a business figure worth grounding-checking,
# and flagging it would make the checker noisy without catching real bugs.
_NUMERIC_RE = re.compile(r"\d[\d.,]*\d|\d{2,}")


@dataclass
class GroundingResult:
    ok: bool
    violations: List[str] = field(default_factory=list)


def verify(answer: str, claims: List[Dict[str, Any]], facts: List[Fact]) -> GroundingResult:
    """Deterministic post-check on Step 3's output - never trusts "must never
    invent business facts" as a prompt instruction alone. Two checks:
    1. every claim must cite a fact_id that actually exists in the manifest
       handed to the model this turn.
    2. every number-like token appearing in the visible answer must appear
       verbatim in at least one fact's text - catches the model stating a
       figure without declaring it as a claim at all."""
    valid_ids = {f.fact_id for f in facts}
    fact_text_blob = "\n".join(f.text for f in facts)
    violations: List[str] = []

    for claim in claims:
        fid = claim.get("fact_id")
        if fid not in valid_ids:
            violations.append(f"claim {claim.get('text')!r} cites unknown fact_id {fid!r}")

    for token in _NUMERIC_RE.findall(answer):
        if token not in fact_text_blob:
            violations.append(f"number {token!r} in answer not traceable to any fact")

    return GroundingResult(ok=not violations, violations=violations)
