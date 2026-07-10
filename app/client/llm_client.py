import json
import os
from typing import Any, Dict, Optional, List
from app.core.llm import llm_provider
from app.models.shopping_context import ShoppingContext

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# $/token, (input, output). Only providers/tiers with a confidently-known
# published rate are listed - unknown combos just log token counts, since a
# guessed price is worse than no price.
_PRICING = {
    "gemini": (0.000000075, 0.000000300),  # gemini-2.5-flash
}

def load_prompt_template(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def _fallback_context(query: str, product_options: Optional[List[Dict[str, Any]]]) -> ShoppingContext:
    """Used when the LLM provider can't be reached at all. Reference
    resolution normally needs the LLM, but if there's exactly one
    previously-shown product we can resolve deterministically without it -
    only ambiguous (2+) cases genuinely require the LLM and have to fall back
    to a raw-text search."""
    if product_options:
        candidates = [p for p in product_options if p.get("slug")]
        if len(candidates) == 1:
            return ShoppingContext(intent="PRODUCT_INFO", product=candidates[0]["slug"])
    return ShoppingContext(intent="SEARCH", query_q=query)

def log_usage(action_name: str, input_tokens: int, output_tokens: int):
    print(f"\n[{llm_provider.name} API Usage - {action_name}]")
    print(f"  - Input Tokens : {input_tokens}")
    print(f"  - Output Tokens: {output_tokens}")
    print(f"  - Total Tokens : {input_tokens + output_tokens}")
    rates = _PRICING.get(llm_provider.name)
    if rates:
        total_cost = input_tokens * rates[0] + output_tokens * rates[1]
        print(f"  - Est. Cost    : ${total_cost:.8f} USD (~{total_cost * 25400:.4f} VND)\n")
    else:
        print("  - Est. Cost    : n/a (no pricing table for this provider)\n")

class LLMClientWrapper:
    async def parse_query(self, query: str, history_str: str, product_options: Optional[List[Dict[str, Any]]] = None) -> ShoppingContext:
        template = load_prompt_template("parser_prompt.txt")

        # Keep this tiny (slug + name only, capped) - it's only here so the
        # LLM can resolve demonstrative references like "cái ở Hà Nội đó".
        options_json = "[]"
        if product_options:
            compact = [
                {"slug": p.get("slug"), "name": p.get("name")}
                for p in product_options[:10] if p.get("slug")
            ]
            if compact:
                options_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

        prompt = template.format(history=history_str, query=query, product_options=options_json)
        if not llm_provider.is_available():
            print(f"\n[{llm_provider.name}] Provider not available. Using deterministic parsing fallback.\n")
            return _fallback_context(query, product_options)
        try:
            result = await llm_provider.generate_structured(
                prompt=prompt,
                response_schema=ShoppingContext,
                model_tier="cheap"
            )
            log_usage("Query Parser", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Parser] {e}. Falling back to default search.\n")
            return _fallback_context(query, product_options)

    async def format_response(self, query: str, history_str: str, evidence_str: str) -> str:
        template = load_prompt_template("formatter_prompt.txt")
        prompt = template.format(history=history_str, query=query, evidence=evidence_str)
        if not llm_provider.is_available():
            print(f"\n[{llm_provider.name}] Provider not available. Using offline response warning.\n")
            return "Xin lỗi bạn, kết nối AI hiện đang gặp gián đoạn. Vui lòng thử lại sau."
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("Response Formatter", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            # Log the real exception server-side for debugging, but never echo
            # it to the user - it used to leak raw provider errors verbatim
            # (provider name, error codes, partial API key fragments like
            # "****EBo=") straight into the chat reply.
            print(f"\n[{llm_provider.name} - Error in Formatter] {e}.\n")
            return "Xin lỗi bạn, kết nối AI hiện đang gặp gián đoạn. Vui lòng thử lại sau."

    async def format_zero_result_response(self, query: str, category: Optional[str]) -> str:
        template = load_prompt_template("zero_result_prompt.txt")
        prompt = template.format(query=query, category=category or "chưa xác định")
        fallback = "Delippy hiện chưa tìm thấy sản phẩm nào khớp với yêu cầu của bạn. Bạn thử tìm với từ khoá khác xem sao nhé!"
        if not llm_provider.is_available():
            print(f"\n[{llm_provider.name}] Provider not available. Using deterministic zero-result fallback.\n")
            return fallback
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("Zero Result Formatter", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Zero Result Formatter] {e}.\n")
            return fallback

    def get_embedding(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        if not text:
            return []

        # 1. Try active provider's embedding first
        try:
            vector = llm_provider.embed(text, task_type=task_type, output_dimensionality=output_dimensionality)
            if vector:
                return vector
        except Exception:
            pass

        # 2. Fallback to Gemini if active provider failed or doesn't support embedding
        if llm_provider.name != "gemini":
            from app.core.llm.factory import get_llm_provider
            try:
                gemini = get_llm_provider("gemini")
                if gemini.is_available():
                    vector = gemini.embed(text, task_type=task_type, output_dimensionality=output_dimensionality)
                    if vector:
                        print(f"\n[LLMClientWrapper] Active provider '{llm_provider.name}' doesn't support embedding. Fell back to Gemini successfully.\n")
                        return vector
            except Exception as e:
                print(f"\n[LLMClientWrapper] Failed to fall back to Gemini for embedding: {e}\n")

        return []

llm_client_wrapper = LLMClientWrapper()
