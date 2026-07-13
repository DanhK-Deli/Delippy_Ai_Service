import re
from typing import Any, Dict, Optional

# Regex-only extraction, no AI - same "Requirement Resolver v0" scope as
# orchestrator.py's _normalize_numeric(). Product names in this catalog spell
# specs out directly (e.g. "Laptop Dell Inspiron 16GB RAM 512GB SSD RTX 4050
# 1.4Kg", "Máy giặt LG Inverter 10.5Kg"), so a name-only regex is enough - no
# catalog field carries these as structured data yet (see compare_builder.py's
# own note on this same gap).
_RAM_RE = re.compile(r"ram\s*(\d+)\s*gb|(\d+)\s*gb\s*ram", re.IGNORECASE)
_SSD_RE = re.compile(r"ssd\s*(\d+)\s*gb|(\d+)\s*gb\s*ssd", re.IGNORECASE)
# Broadened past just "RTX/GTX <model>" to catch generic "card/vga rời" and
# "radeon" phrasing too - matters more now that a NON-match is read as a real
# "no dedicated GPU" (see SpecExtractor's own note below), so recall on
# detecting a GPU mention matters more than it did when absence was neutral.
_GPU_RE = re.compile(
    r"\b(?:rtx|gtx)\s*\d+|radeon\s*\d|(?:card|vga)\s*(?:đồ\s*họa\s*)?rời",
    re.IGNORECASE,
)
# Shared by washing-machine capacity and laptop weight - same "<number>Kg"
# shape, just read by two different extractor methods.
_KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)
_INVERTER_RE = re.compile(r"inverter", re.IGNORECASE)

def _first_int(pattern: re.Pattern, text: str) -> Optional[int]:
    match = pattern.search(text)
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None

class SpecExtractor:
    """Parses raw product name/details text into the structured spec
    attributes app/knowledge/guide_rule.json scores against (see
    recommendation_builder.py) - a lightweight registry keyed by the same
    category-group keys as guide_rule.json/compare_rule.json ("tech" for
    laptops, "appliance" for washing machines this sprint). A group with no
    dedicated extractor here just gets an empty dict back -
    recommendation_builder already treats "no guide_rule.json entry" as
    "don't score", so this never needs a fallback path.

    Numeric specs (ram/ssd/capacity/weight_kg) stay None when not found -
    "not mentioned" can't be assumed to mean "0", so recommendation_builder
    skips scoring/warning on those entirely rather than guessing.

    Boolean specs (gpu/inverter) are the deliberate exception: they resolve
    to an explicit True/False, never None. On this marketplace a discrete
    GPU or an Inverter compressor is a headline selling point sellers always
    put in the title - so "not mentioned" is a reasonably reliable negative
    signal here, not just missing data. That's what lets
    recommendation_builder raise a real "⚠ không có Inverter..." warning
    instead of silently skipping the attribute - a v0 heuristic scoped to
    this catalog's naming conventions, not a general rule for every spec."""

    def extract(self, group: Optional[str], text: str) -> Dict[str, Any]:
        text = text or ""
        if group == "tech":
            return self._extract_tech(text)
        if group == "appliance":
            return self._extract_appliance(text)
        return {}

    def _extract_tech(self, text: str) -> Dict[str, Any]:
        specs: Dict[str, Any] = {}
        ram = _first_int(_RAM_RE, text)
        if ram is not None:
            specs["ram"] = ram
        ssd = _first_int(_SSD_RE, text)
        if ssd is not None:
            specs["ssd"] = ssd
        weight_match = _KG_RE.search(text)
        if weight_match:
            specs["weight_kg"] = float(weight_match.group(1).replace(",", "."))
        specs["gpu"] = bool(_GPU_RE.search(text))
        return specs

    def _extract_appliance(self, text: str) -> Dict[str, Any]:
        specs: Dict[str, Any] = {}
        match = _KG_RE.search(text)
        if match:
            specs["capacity"] = float(match.group(1).replace(",", "."))
        specs["inverter"] = bool(_INVERTER_RE.search(text))
        return specs

spec_extractor = SpecExtractor()
