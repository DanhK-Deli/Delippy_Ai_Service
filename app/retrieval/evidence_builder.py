from typing import List, Dict, Any, Optional
from app.models.evidence import Evidence

class EvidenceBuilder:
    def build_search_evidence(self, products: List[Dict[str, Any]]) -> Evidence:
        cleaned_products = []
        # Keep a full page (backend returns up to 20/request) so "xem thêm"
        # pagination has something to page through - only the first 5 are
        # ever shown or sent to the LLM at once (see response_formatter.py).
        for p in products[:20]:
            cleaned_products.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "slug": p.get("slug"),
                "thumbnail": p.get("thumbnail"),
                "price": p.get("price"),
                "original_price": p.get("original_price"),
                "discount_percent": p.get("discount_percent"),
                "rating": p.get("rating"),
                "sold_count": p.get("sold_count"),
                "stock": p.get("stock")
            })
        return Evidence(products=cleaned_products)

    def build_comparison_evidence(
        self,
        target_details: List[Dict[str, Any]],
        not_found: Optional[List[str]] = None,
        suggestions: Optional[List[Dict[str, Any]]] = None,
    ) -> Evidence:
        cleaned_comparisons = []
        for d in target_details:
            # Only keep size names (price already shown at top level) and cap
            # list lengths - comparisons stack up to 3 products into one LLM
            # prompt, so per-product payload size matters for token cost.
            size_names = [s.get("name") for s in d.get("sizes", []) if isinstance(s, dict) and s.get("name")][:5]
            colors = [c for c in d.get("variant_colors", []) if isinstance(c, str)][:5]

            cleaned_comparisons.append({
                "name": d.get("name"),
                "price": d.get("price"),
                "rating": d.get("rating"),
                "sold_count": d.get("sold_count"),
                "details": d.get("details", "")[:300],  # Keep short summary of details
                "stock": d.get("stock"),
                "sizes": size_names,
                "colors": colors
            })

        cleaned_suggestions = []
        for s in (suggestions or [])[:3]:
            cleaned_suggestions.append({
                "name": s.get("name"),
                "price": s.get("price"),
                "slug": s.get("slug")
            })

        return Evidence(
            comparison_results=cleaned_comparisons,
            not_found=not_found or [],
            related_products=cleaned_suggestions
        )

    def build_detail_evidence(self, detail: Dict[str, Any], reviews_summary: Optional[Dict[str, Any]] = None, related: List[Dict[str, Any]] = None) -> Evidence:
        cleaned_detail = {
            "name": detail.get("name"),
            "price": detail.get("price"),
            "original_price": detail.get("original_price"),
            "stock": detail.get("stock"),
            "rating": detail.get("rating"),
            "sold_count": detail.get("sold_count"),
            "details": detail.get("details", "")[:500],
            "sizes": detail.get("sizes", []),
            "colors": detail.get("variant_colors", [])
        }
        
        cleaned_related = []
        if related:
            for r in related[:3]:
                cleaned_related.append({
                    "name": r.get("name"),
                    "price": r.get("price"),
                    "slug": r.get("slug")
                })
                
        return Evidence(
            details=cleaned_detail,
            faq_answer=f"Đánh giá TB: {reviews_summary.get('average_rating')} ({reviews_summary.get('total_reviews')} đánh giá)" if reviews_summary else None,
            related_products=cleaned_related
        )

evidence_builder = EvidenceBuilder()
