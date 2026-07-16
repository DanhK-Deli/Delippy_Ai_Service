import json
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from app.help.templates import is_template_ready
from app.knowledge.help.loader import help_knowledge

# Human-readable labels for the Vietnamese {{placeholder}} field names
# app/help/business_object_executor.py's _flatten_into_context writes into
# context - only used to phrase backend facts readably for Step 3, not a
# second source of truth for the values themselves.
_FIELD_LABELS = {
    "ma_don_hang": "Mã đơn hàng",
    "trang_thai_hien_tai": "Trạng thái hiện tại",
    "moc_tracking_gan_nhat": "Mốc tracking gần nhất",
    "thoi_gian_giao": "Thời gian giao",
    "so_tien": "Số tiền",
    "danh_sach_phuong_thuc": "Danh sách phương thức thanh toán",
    "thoi_gian_dong_bo_du_kien": "Thời gian đồng bộ dự kiến",
    "thong_tin_seller": "Thông tin người bán",
    "display_name": "Tên hiển thị",
    "default_address": "Địa chỉ mặc định",
    # Entity keys collected via slot-filling (app/help/orchestrator.py's
    # _ENTITY_QUESTIONS) - without a label these showed up in facts as raw
    # snake_case ("san_pham_can_doi_tra: trả toàn bộ đơn"), which read to the
    # customer like an internal system ID (confirmed live).
    "san_pham_can_doi_tra": "Sản phẩm muốn đổi trả",
    "ly_do_doi_tra": "Lý do đổi trả",
    "hinh_anh_minh_chung": "Hình ảnh minh chứng",
    "dia_chi_giao_moi": "Địa chỉ giao mới",
    "ma_voucher": "Mã voucher",
    "ma_yeu_cau_doi_tra": "Mã yêu cầu đổi trả",
    "kenh_dang_nhap": "Kênh đăng nhập",
    "kenh_nghi_ngo_lua_dao": "Kênh nghi ngờ lừa đảo",
    "san_pham": "Sản phẩm",
    "so_dien_thoai_hoac_email": "Số điện thoại/email",
    "so_dien_thoai": "Số điện thoại",
    "ma_van_don": "Mã vận đơn",
    "don_vi_van_chuyen": "Đơn vị vận chuyển",
    "chua_ban_giao_van_chuyen": "Tình trạng bàn giao vận chuyển",
    "thoi_gian_van_chuyen_tham_khao": "Thời gian giao trung bình tham khảo (không phải cam kết chính thức)",
}


@dataclass
class Fact:
    fact_id: str
    source: str
    text: str


def _backend_facts(context: Dict[str, Any], system_keys: Set[str]) -> List[Fact]:
    facts: List[Fact] = []
    i = 1
    for k, v in context.items():
        if k in system_keys or v in (None, "", [], {}):
            continue
        label = _FIELD_LABELS.get(k, k)
        facts.append(Fact(fact_id=f"B{i}", source="backend", text=f"{label}: {v}"))
        i += 1
    return facts


def _json_source_facts(business_object_ids: List[str]) -> List[Fact]:
    """Resolves each business object's json_sources into facts: the KO's own
    business_rules[] (always usable, these are concrete written written
    conditions, not placeholders) plus its success template content - but
    ONLY for business objects that are NEITHER mutating NOR escalate_always.

    Why the exclusion: a KO's response_templates.success_response is an
    OUTCOME-ANNOUNCEMENT template ("Mình đã huỷ đơn hàng ... thành công rồi
    nhé!") written for v1's "render AFTER confirming the action actually
    succeeded" pattern - it describes something that MAY become true, not
    something that already is. Feeding it into the fact manifest
    unconditionally is a category error: Step 3 has no way to tell "this is
    neutral background info" apart from "this is a hypothetical success
    message", and will happily copy the latter as if it were an established
    fact (confirmed live: order cancellation never ran, but RT_ORDER_CANCEL_
    SUCCESS's exact wording still showed up as the answer, because it was
    sitting right there in the facts list with nothing marking it
    conditional). For static informational KOs (POLICY_*, COMPANY_INTRO...)
    the success template genuinely IS neutral content and stays included.
    The real "did the action happen" fact for mutating objects comes from
    _action_result_fact() below instead, driven by what actually ran."""
    facts: List[Fact] = []
    seen: Set[tuple] = set()
    i = 1
    for bo_id in business_object_ids:
        bo = help_knowledge.get_business_object(bo_id) or {}
        skip_outcome_template = bool(bo.get("mutating") or bo.get("escalate_always"))
        for src in bo.get("json_sources") or []:
            domain_attr, ko_id = src.get("domain_attr"), src.get("ko_id")
            key = (domain_attr, ko_id)
            if key in seen:
                continue
            seen.add(key)
            ko = help_knowledge.get_knowledge_object_by_id(domain_attr, ko_id)
            if not ko:
                continue
            for rule in ko.get("business_rules") or []:
                facts.append(Fact(fact_id=f"J{i}", source=f"{domain_attr}.{ko_id}", text=rule))
                i += 1
            # app_flows.json records (real UI navigation - see docs/chatbot-
            # cskh-knowledge-base-design.md): blocked_message ALWAYS wins and
            # steps are NEVER surfaced for a BLOCKED (🔴) flow - the source
            # doc is explicit that guiding "vào mục X" when X has no real
            # entry point in the UI leaves the customer stuck looking for a
            # button that doesn't exist.
            blocked_message = ko.get("blocked_message")
            if blocked_message:
                facts.append(Fact(fact_id=f"J{i}", source=f"{domain_attr}.{ko_id}.status", text=blocked_message))
                i += 1
            if ko.get("status") != "BLOCKED":
                for step in ko.get("steps") or []:
                    facts.append(Fact(fact_id=f"J{i}", source=f"{domain_attr}.{ko_id}.steps", text=step))
                    i += 1
            if skip_outcome_template:
                continue
            template_id = (ko.get("response_templates") or {}).get("success_response")
            template = help_knowledge.get_template(template_id) if template_id else None
            # is_template_ready() only screens for TODO/MISSING_FROM_DOCUMENT -
            # several templates (RT_SHIP_STAGE_5_IN_TRANSIT_WITH_ETA,
            # RT_POLICY_SUMMARY...) still carry real {{placeholder}} syntax
            # that v1's flow_executor used to fill via per-KO custom render
            # logic this generic json_sources pipeline has no equivalent for.
            # Surfacing the raw "{{ma_van_don}}" text as a fact is strictly
            # worse than omitting it - the real value is already its own
            # backend fact anyway (confirmed live: this showed up verbatim).
            if template and is_template_ready(template) and "{{" not in template["content"]:
                facts.append(Fact(fact_id=f"J{i}", source=f"{domain_attr}.{ko_id}.{template_id}", text=template["content"]))
                i += 1
    return facts


def build(business_object_ids: List[str], context: Dict[str, Any], system_keys: Set[str]) -> List[Fact]:
    return _backend_facts(context, system_keys) + _json_source_facts(business_object_ids)


def action_result_fact(action_label: str) -> Fact:
    """The ONLY fact orchestrator.py is allowed to add saying a mutating
    action (cancel order, delete account...) actually completed - added
    exclusively when business_object_executor.ExecutionResult.mutating_
    completed is True this turn, never speculatively. Step 3's prompt is
    told explicitly: no claiming an action completed without this fact."""
    return Fact(fact_id="ACT1", source="action_result", text=f"Kết quả hành động: {action_label} đã hoàn tất thành công.")


def to_json(facts: List[Fact]) -> str:
    return json.dumps([{"fact_id": f.fact_id, "text": f.text} for f in facts], ensure_ascii=False)
