import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class HelpKnowledgeValidationError(RuntimeError):
    """Raised on startup (APP_ENV=production only) when an enabled intent
    still carries a TODO/MISSING_FROM_DOCUMENT placeholder. See manifest.json's
    disabled_intents for the opt-out escape hatch (soft-launch a domain whose
    content isn't finished yet without blocking the whole /help service)."""


class HelpKnowledge:
    """Singleton registry for the /help (CSKH) knowledge base in this
    directory - one attribute per JSON file, mirroring app/knowledge/ontology.py's
    Ontology one directory up (same __new__/_load_json pattern). Business-domain
    files (01-13, each a list of Knowledge Objects under "knowledge_objects")
    and infra files (14-18: tool/dictionary/response_template/business_flow/
    error_message registries) all load the same way; only the fail-fast TODO
    check is scoped to knowledge_objects, since a TODO in an infra registry is
    already an explicit, visible status/content flag (e.g. tool.json's
    _status_legend), not a silent gap in what the bot will say.

    JSON is the source of truth: editing a domain file and letting
    maybe_reload() pick up the change is the entire "deploy", no LLM retrain,
    no prompt edit, no service restart.
    """

    _instance = None

    _DOMAIN_FILES: Dict[str, str] = {
        "company": "company.json",
        "account": "account.json",
        "order": "order.json",
        "payment": "payment.json",
        "shipping": "shipping.json",
        "return_refund": "return_refund.json",
        "warranty": "warranty.json",
        "profile": "profile.json",
        "promotion": "promotion.json",
        "policy": "policy.json",
        "security": "security.json",
        "contact": "contact.json",
        "faq": "faq.json",
    }
    _INFRA_FILES: Dict[str, str] = {
        "error_message": "error_message.json",
        "tool": "tool.json",
        "dictionary": "dictionary.json",
        "response_template": "response_template.json",
        "business_flow": "business_flow.json",
    }
    _MANIFEST_ATTR = "manifest"
    _MANIFEST_FILE = "manifest.json"

    _PLACEHOLDER_MARKERS = ("TODO", "MISSING_FROM_DOCUMENT")

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(HelpKnowledge, cls).__new__(cls)
            cls._instance._mtimes = {}
            cls._instance.reload()
        return cls._instance

    def _all_files(self) -> Dict[str, str]:
        return {**self._DOMAIN_FILES, **self._INFRA_FILES, self._MANIFEST_ATTR: self._MANIFEST_FILE}

    @classmethod
    def domain_attrs(cls) -> Tuple[str, ...]:
        """Public accessor for the 13 business-domain attribute names (e.g.
        "order", "payment") - used by app/help/rule_engine.py so it doesn't
        have to reach into the private _DOMAIN_FILES map directly."""
        return tuple(cls._DOMAIN_FILES.keys())

    def reload(self, only: Optional[str] = None):
        """Reload every file (only=None - the startup path, from __new__) or
        just one attribute (only="shipping", etc - the hot-reload path, see
        maybe_reload()). Fail-fast validation only runs on the only=None
        (startup) path - see class docstring on why a single hot-reloaded
        file never raises, even under APP_ENV=production."""
        base_dir = os.path.dirname(__file__)
        all_files = self._all_files()
        targets = {only: all_files[only]} if only else all_files
        for attr, filename in targets.items():
            path = os.path.join(base_dir, filename)
            setattr(self, attr, self._load_json(path))
            self._mtimes[attr] = self._safe_mtime(path)
        if only is None:
            self._validate_or_raise()

    def maybe_reload(self) -> List[str]:
        """Cheap per-call check: stat() every tracked file and reload ONLY
        the ones whose mtime moved since last load. No file-watcher dependency
        (watchdog isn't in requirements.txt) - a stat() call per file is
        negligible next to an LLM round trip. Never raises, even under
        APP_ENV=production (see reload()'s only=None note); logs a warning
        instead so a bad edit is visible in production logs without taking
        the service down mid-traffic. Returns the list of attribute names
        that were actually reloaded (empty if nothing changed)."""
        base_dir = os.path.dirname(__file__)
        changed = []
        for attr, filename in self._all_files().items():
            path = os.path.join(base_dir, filename)
            current = self._safe_mtime(path)
            if current != self._mtimes.get(attr):
                self.reload(only=attr)
                changed.append(attr)
        if changed:
            logger.info(f"[HelpKnowledge] hot-reloaded changed file(s): {changed}")
            self._log_placeholder_warning_if_any()
        return changed

    def _load_json(self, path: str) -> Any:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception:
            logger.exception(f"[HelpKnowledge] failed to load {path}")
            return {}

    def _safe_mtime(self, path: str) -> Optional[float]:
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    # ── Validation ───────────────────────────────────────────────────────────

    def find_placeholders(self) -> List[Tuple[str, str, str]]:
        """(domain_attr, knowledge_object_id, field_path) for every
        TODO/MISSING_FROM_DOCUMENT placeholder still present in an enabled
        Knowledge Object (business-domain files only). Skips ids listed in
        manifest.json's disabled_intents."""
        disabled = set((getattr(self, self._MANIFEST_ATTR, None) or {}).get("disabled_intents", []))
        issues = []
        for attr in self._DOMAIN_FILES:
            data = getattr(self, attr, None) or {}
            for ko in data.get("knowledge_objects", []):
                ko_id = ko.get("id", "<no id>")
                if ko_id in disabled:
                    continue
                for field_path in self._scan(ko):
                    issues.append((attr, ko_id, field_path))
        return issues

    def _scan(self, value: Any, path: str = "") -> List[str]:
        hits: List[str] = []
        if isinstance(value, str):
            if any(marker in value for marker in self._PLACEHOLDER_MARKERS):
                hits.append(path or "<root>")
        elif isinstance(value, dict):
            for k, v in value.items():
                hits += self._scan(v, f"{path}.{k}" if path else str(k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                hits += self._scan(v, f"{path}[{i}]")
        return hits

    def _summarize(self, issues: List[Tuple[str, str, str]]) -> str:
        by_domain: Dict[str, int] = {}
        for attr, _, _ in issues:
            by_domain[attr] = by_domain.get(attr, 0) + 1
        return ", ".join(f"{d}={n}" for d, n in sorted(by_domain.items()))

    def find_broken_references(self) -> List[str]:
        """Structural integrity check across the whole KB - complements
        find_placeholders() (which only scans for TODO/MISSING_FROM_DOCUMENT
        text) with referential/logical checks that permanently productionize
        the ad hoc cross-check script used while authoring this JSON:
        - api_mapping[].tool_id resolves in tool.json
        - response_templates.success_response/failure_response resolve in
          response_template.json
        - required_entities is a subset of that Knowledge Object's own
          entities list
        - related_intents values are real intents somewhere in the KB
        - business_flow.json covers every Knowledge Object exactly once (no
          orphan either direction)
        - every Knowledge Object has a non-empty escalation_rules (the
          Business Document's own stated rule for 18_business_flow: no flow
          may dead-end without a way out to CSKH)
        Same severity model as find_placeholders() - see _validate_or_raise().
        Returns a flat list of human-readable issue strings (not tuples,
        since these span several different kinds of reference, not just one
        field path each)."""
        disabled = set((getattr(self, self._MANIFEST_ATTR, None) or {}).get("disabled_intents", []))
        tool_ids = {t.get("id") for t in (getattr(self, "tool", None) or {}).get("tools", [])}
        template_ids = {t.get("id") for t in (getattr(self, "response_template", None) or {}).get("templates", [])}
        flow_ids = {f.get("id") for f in (getattr(self, "business_flow", None) or {}).get("flows", [])}

        kos_by_domain: Dict[str, List[Dict[str, Any]]] = {
            attr: (getattr(self, attr, None) or {}).get("knowledge_objects", []) for attr in self._DOMAIN_FILES
        }
        all_ko_ids = {ko.get("id") for kos in kos_by_domain.values() for ko in kos}
        all_intents = {ko.get("intent") for kos in kos_by_domain.values() for ko in kos if ko.get("intent")}

        issues: List[str] = []
        for attr, kos in kos_by_domain.items():
            for ko in kos:
                ko_id = ko.get("id", "<no id>")
                if ko_id in disabled:
                    continue
                for api in (ko.get("api_mapping") or []):
                    tool_id = api.get("tool_id")
                    if tool_id and tool_id not in tool_ids:
                        issues.append(f"{attr}.{ko_id}: api_mapping references unknown tool_id {tool_id!r}")
                response_templates = ko.get("response_templates") or {}
                for key in ("success_response", "failure_response"):
                    val = response_templates.get(key)
                    if isinstance(val, str) and val.startswith("RT_") and val not in template_ids:
                        issues.append(f"{attr}.{ko_id}: response_templates.{key} references unknown template {val!r}")
                entities = set(ko.get("entities") or [])
                for req in (ko.get("required_entities") or []):
                    if req not in entities:
                        issues.append(f"{attr}.{ko_id}: required_entities has {req!r} not listed in entities")
                for rel in (ko.get("related_intents") or []):
                    if rel not in all_intents:
                        issues.append(f"{attr}.{ko_id}: related_intents references unknown intent {rel!r}")
                if not ko.get("escalation_rules"):
                    issues.append(f"{attr}.{ko_id}: no escalation_rules - flow may dead-end without a way out to CSKH")
                if ko_id not in flow_ids:
                    issues.append(f"{attr}.{ko_id}: missing from business_flow.json (orphan knowledge object)")

        for flow_id in flow_ids:
            if flow_id not in all_ko_ids:
                issues.append(f"business_flow.json: orphan flow entry {flow_id!r} (no matching knowledge object)")
        return issues

    def _validate_or_raise(self):
        """Startup-only gate (see reload()). Dev/staging: log and continue.
        Production: refuse to start. Combines the text-placeholder scan and
        the structural integrity scan into one gate - both are "content not
        ready for production" in the same sense."""
        placeholder_issues = self.find_placeholders()
        reference_issues = self.find_broken_references()
        if not placeholder_issues and not reference_issues:
            return
        parts = []
        if placeholder_issues:
            parts.append(
                f"{len(placeholder_issues)} TODO/MISSING_FROM_DOCUMENT placeholder(s) "
                f"({self._summarize(placeholder_issues)})"
            )
        if reference_issues:
            parts.append(f"{len(reference_issues)} structural integrity issue(s): " + "; ".join(reference_issues[:10]) +
                          (" ..." if len(reference_issues) > 10 else ""))
        message = " and ".join(parts) + "."
        if settings.APP_ENV == "production":
            raise HelpKnowledgeValidationError(
                f"{message} Fill placeholders in / fix references, or add affected knowledge_object "
                f"id(s) to manifest.json's disabled_intents to soft-launch without them. Refusing to "
                f"start with APP_ENV=production."
            )
        logger.warning(
            f"[HelpKnowledge] {message} Allowed under APP_ENV={settings.APP_ENV!r}; this WILL fail "
            f"fast under APP_ENV=production."
        )

    def _log_placeholder_warning_if_any(self):
        """Same checks as _validate_or_raise() but NEVER raises - used after a
        hot-reload so a bad edit is visible in logs without taking a live
        production service down mid-traffic."""
        placeholder_issues = self.find_placeholders()
        reference_issues = self.find_broken_references()
        if placeholder_issues or reference_issues:
            logger.warning(
                f"[HelpKnowledge] hot-reload left {len(placeholder_issues)} TODO/MISSING_FROM_DOCUMENT "
                f"placeholder(s) ({self._summarize(placeholder_issues)}) and {len(reference_issues)} "
                f"structural integrity issue(s)."
            )

    # ── Convenience lookups ──────────────────────────────────────────────────

    @property
    def kb_version(self) -> str:
        return (getattr(self, self._MANIFEST_ATTR, None) or {}).get("kb_version", "unknown")

    def get_knowledge_object(self, domain_attr: str, intent: str) -> Optional[Dict[str, Any]]:
        data = getattr(self, domain_attr, None) or {}
        for ko in data.get("knowledge_objects", []):
            if ko.get("intent") == intent:
                return ko
        return None

    def get_tool(self, tool_id: str) -> Optional[Dict[str, Any]]:
        for t in (getattr(self, "tool", None) or {}).get("tools", []):
            if t.get("id") == tool_id:
                return t
        return None

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        for t in (getattr(self, "response_template", None) or {}).get("templates", []):
            if t.get("id") == template_id:
                return t
        return None


help_knowledge = HelpKnowledge()
