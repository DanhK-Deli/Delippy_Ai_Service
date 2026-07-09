from typing import List
from pydantic import BaseModel, Field
from app.core.llm import llm_provider
from app.client.llm_client import log_usage

class _ExpansionResult(BaseModel):
    is_real_product_term: bool = Field(
        description="true nếu từ khóa gốc trông giống tên/mô tả một mặt hàng thực sự (kể cả viết tắt, tiếng lóng, sai chính tả nhẹ); false nếu là chuỗi vô nghĩa, ký tự/số ngẫu nhiên, hoặc rõ ràng không phải tên sản phẩm nào cả"
    )
    variants: List[str] = Field(
        default_factory=list,
        description="CHỈ điền khi is_real_product_term=true: 2-4 cụm từ khóa tìm kiếm thay thế (đồng nghĩa/tên gọi khác/mặt hàng liên quan gần), viết thường, không trùng nhau, không lặp lại từ khóa gốc. Để trống [] khi is_real_product_term=false - đừng cố bịa ra từ khóa liên quan."
    )

class QueryExpander:
    """Tier-2 (lazy) expansion: only called when a search already came back
    with 0 results, as a direct replacement for the old "ask the user to
    teach the system" loop - same trigger point, but instead of writing an
    unreviewed alias into a shared file, it just generates retry variants for
    this one request and throws them away afterwards. Deliberately a tiny,
    standalone prompt (no history, no intent schema) so it's cheap - this is
    the whole point of keeping it lazy instead of running on every query."""

    async def expand(self, query_q: str) -> List[str]:
        if not query_q or not llm_provider.is_available():
            return []

        prompt = (
            "Từ khóa tìm kiếm sau đây trên một sàn thương mại điện tử không ra kết quả nào: "
            f"'{query_q}'.\n"
            "Trước tiên xác định đây có phải tên/mô tả một mặt hàng thực sự không (kể cả viết tắt, "
            "tiếng lóng, gõ sai). Nếu KHÔNG phải (chuỗi vô nghĩa, ký tự ngẫu nhiên, rác) thì để "
            "variants rỗng - đừng cố bịa ra từ khóa nghe có vẻ liên quan.\n"
            "Nếu ĐÚNG là một mặt hàng thực sự, đề xuất 2-4 cụm từ khóa THAY THẾ (đồng nghĩa, tên gọi "
            "khác, hoặc mặt hàng liên quan gần) để thử tìm kiếm lại."
        )
        try:
            result = await llm_provider.generate_structured(
                prompt=prompt,
                response_schema=_ExpansionResult,
                model_tier="cheap",
            )
            log_usage("Query Expander", result.prompt_tokens, result.completion_tokens)
            if not result.value.is_real_product_term:
                print(f"[QueryExpander] '{query_q}' looks like gibberish/not a product term - skipping expansion.")
                return []
            variants = [v.strip().lower() for v in result.value.variants if v and v.strip()]
            variants = [v for v in variants if v != query_q.strip().lower()]
            print(f"[QueryExpander] '{query_q}' -> {variants}")
            return variants
        except Exception as e:
            print(f"[QueryExpander] Error expanding '{query_q}': {e}")
            return []

query_expander = QueryExpander()
