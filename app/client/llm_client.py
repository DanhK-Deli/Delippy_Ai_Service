import contextvars
import json
import os
import threading
from typing import Any, Dict, Optional, List
from app.core.llm import llm_provider
from app.models.shopping_context import ShoppingContext
from app.models.ai_scorer import AIScorerResponse
from app.understanding.intent_classifier import strip_no_preference_phrasing
from app.understanding.entity_extractor import entity_extractor

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# Accumulates total token usage (input+output) across every LLM call made
# during the lifespan of a single incoming API request - each request is
# handled in its own asyncio Task (FastAPI/Starlette), and a ContextVar's
# value is scoped to that Task's context, so concurrent requests never see
# each other's running total. Callers (app/help/orchestrator.py,
# app/chat/orchestrator.py) reset it to 0 at the start of process_*_message()
# and read the final value right before returning, to report `tokens_used`
# in the response for debug/observability purposes.
request_tokens: contextvars.ContextVar[int] = contextvars.ContextVar("request_tokens", default=0)

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
    cleaned_query = strip_no_preference_phrasing(query) or query

    # A bare price-narrowing reply ("dưới 500k") has no product noun of its
    # own - memory_resolver.resolve() is built to detect exactly that (see its
    # own "dưới 500k" comment) and carry the PRIOR turn's real query_q/category
    # forward instead, but only when THIS turn's query_q is falsy. The normal
    # AI parser path already leaves query_q null for these replies (it has
    # conversation history to recognize them); this fallback has neither
    # history nor an LLM to make that call, so without this check it echoed
    # the raw price phrase back as query_q on every Gemini timeout/error,
    # which memory_resolver then reads as a brand-new, unrelated topic and
    # wipes the real category/brand/price it was supposed to narrow.
    # Confirmed live: "tìm sữa" (category=sieu-thi-bach-hoa) -> too-vague
    # clarifying question -> "dưới 500" hit a Gemini timeout -> fell back to
    # a literal "dưới 500" text search with category wiped, 0 results.
    entities = entity_extractor.extract(cleaned_query)
    has_price = entities["price_min"] is not None or entities["price_max"] is not None
    leftover = [w for w in entity_extractor.clean_query_keywords(cleaned_query).split() if not w.isdigit()]
    query_q = None if (has_price and not leftover) else cleaned_query
    return ShoppingContext(
        intent="SEARCH",
        query_q=query_q,
        price_min=entities["price_min"],
        price_max=entities["price_max"],
    )

def log_usage(action_name: str, input_tokens: int, output_tokens: int):
    request_tokens.set(request_tokens.get() + input_tokens + output_tokens)
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


_nomic_tokenizer = None
_nomic_model = None
_nomic_lock = threading.Lock()

def _get_nomic_model():
    global _nomic_tokenizer, _nomic_model
    with _nomic_lock:
        if _nomic_model is None:
            import torch
            from transformers import AutoTokenizer, AutoModel
            
            # Check if local model folder exists in workspace
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            local_path = os.path.join(base_dir, "models", "nomic-embed")
            
            if os.path.exists(local_path):
                model_path = local_path
                print(f"\n[Embedding] Loading nomic-embed from local directory: '{model_path}'")
            else:
                model_path = "nomic-ai/nomic-embed-text-v1.5"
                print(f"\n[Embedding] Local directory not found. Loading nomic-embed from Hugging Face: '{model_path}'")
                
            _nomic_tokenizer = AutoTokenizer.from_pretrained(model_path)
            _nomic_model = AutoModel.from_pretrained(model_path, trust_remote_code=True)
    return _nomic_tokenizer, _nomic_model


_nomic_inference_lock = threading.Lock()

def _nomic_embed(text: str, task_type: Optional[str] = None) -> List[float]:
    import torch
    import torch.nn.functional as F
    
    tokenizer, model = _get_nomic_model()
    
    is_query = task_type in ("search_query", "RETRIEVAL_QUERY", "query") or (task_type is None)
    prefix = "search_query: " if is_query else "search_document: "
    formatted_text = prefix + text
    
    with _nomic_inference_lock:
        encoded_input = tokenizer([formatted_text], padding=True, truncation=True, return_tensors='pt')
        with torch.no_grad():
            model_output = model(**encoded_input)
            
        token_embeddings = model_output[0]
        input_mask_expanded = encoded_input['attention_mask'].unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        embeddings = sum_embeddings / sum_mask
        
        embeddings = F.normalize(embeddings, p=2, dim=1)
        return embeddings[0].tolist()



class LLMClientWrapper:
    async def parse_query(
        self, query: str, history_str: str, product_options: Optional[List[Dict[str, Any]]] = None,
        examples: str = "",
    ) -> ShoppingContext:
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

        prompt = template.format(history=history_str, query=query, product_options=options_json, examples=examples)
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

    async def format_faq_response(self, query: str, history_str: str, policy_text: str) -> str:
        template = load_prompt_template("faq_prompt.txt")
        prompt = template.format(history=history_str, query=query, policy=policy_text or "")
        if not llm_provider.is_available():
            return "Xin lỗi bạn, kết nối AI hiện đang gặp gián đoạn. Vui lòng thử lại sau."
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("FAQ Formatter", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in FAQ Formatter] {e}.\n")
            return "Xin lỗi bạn, kết nối AI hiện đang gặp gián đoạn. Vui lòng thử lại sau."

    async def format_zero_result_response(self, query: str, render_context: Dict[str, Any]) -> str:
        template = load_prompt_template("zero_result_prompt.txt")
        prompt = template.format(
            query=query,
            render_type=render_context.get("type", "none"),
            render_count=render_context.get("count", 0)
        )
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

    async def format_education_response(self, term: str, choices: List[Dict[str, Any]]) -> Optional[str]:
        """Market-education paragraph shown BEFORE the Consultation Flow's
        first gap-fill question (see orchestrator.py) - explains the buying
        choices for a still-wide-open "tư vấn X" ask, deliberately never
        mentioning a real product/brand (none has been searched yet at this
        point). Returns None on any failure so the caller can fall back to
        the plain deterministic clarifying question instead of blocking the
        whole Consultation Flow on this one extra LLM call."""
        template = load_prompt_template("education_prompt.txt")
        choices_json = json.dumps(choices, ensure_ascii=False, separators=(",", ":"))
        prompt = template.format(term=term, choices=choices_json)
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("Education", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Education] {e}.\n")
            return None

    async def format_tech_explain_response(self, category: str, question: str) -> Optional[str]:
        """Neutral technology explainer (Sprint 4's Tech Explain, Bước 2.2) -
        the LLM fallback for a "tại sao/vì sao/... hay ..." question tied to
        an already-active category that guide_rule.json has no matching spec
        for (see recommendation_builder.match_spec_education, tried FIRST by
        the caller so this only runs on an actual miss). Returns None on any
        failure so the caller can silently let the turn fall through to the
        normal pipeline instead of surfacing a broken response."""
        template = load_prompt_template("tech_explain_prompt.txt")
        prompt = template.format(category=category, question=question)
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("Tech Explain", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Tech Explain] {e}.\n")
            return None

    async def format_comparison_analysis(self, query: str, products: List[Dict[str, Any]]) -> Optional[str]:
        """Generates a semantic comparison paragraph (1-2 sentences) from LLM comparing product features/tastes/use-cases."""
        template = load_prompt_template("compare_analysis_prompt.txt")
        products_json = json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        prompt = template.format(products=products_json)
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="cheap"
            )
            log_usage("Compare Analysis", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Compare Analysis] {e}.\n")
            return None


    async def score_products_ai(self, need_text: str, catalog: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Runs the generalist Tier B AI Scorer (Zero-Shot) when a category has no guide_rule.json definition.
        Reads the user requirements description and the raw product names/details, and outputs the structured
        suitability scores and reasoning bullets under the AIScorerResponse schema."""
        template = load_prompt_template("ai_scorer_prompt.txt")
        prompt = template.format(
            need=need_text,
            products=json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        )
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_structured(
                prompt=prompt,
                response_schema=AIScorerResponse,
                model_tier="cheap"
            )
            log_usage("AI Scorer (Long-tail)", result.prompt_tokens, result.completion_tokens)
            return [item.model_dump() for item in result.value.products]
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in AI Scorer] {e}.\n")
            return None

    async def format_product_deep_dive(
        self, product_name: str, seller_description: Optional[str], price: Optional[float],
    ) -> Optional[str]:
        """Genuine deeper analysis for a specific, already-selected product -
        every PRODUCT_INFO turn gets this now, not just an explicit "tư vấn
        kỹ hơn về X" ask (see orchestrator.py's PRODUCT_INFO branch). The
        seller's own `details` text is often too sparse to actually consult
        from (just a hotline number/warranty terms, see the live example
        that prompted this), so this draws on the LLM's own real market
        knowledge about that product/model instead, honestly declining if it
        doesn't recognize the specific model rather than inventing specs.
        Returns None on any failure so the caller falls back to the plain
        description snippet."""
        template = load_prompt_template("product_deep_dive_prompt.txt")
        prompt = template.format(
            product_name=product_name,
            price=f"{price:,.0f}" if price is not None else "chưa rõ",
            seller_description=(seller_description or "(không có mô tả)")[:500],
        )
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_text(
                prompt=prompt,
                model_tier="deep_dive"
            )
            log_usage("Product Deep Dive", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Product Deep Dive] {e}.\n")
            return None

    async def format_product_focus_reply(
        self, product_name: str, focus: Dict[str, bool],
        price: Optional[float], stock: Optional[int],
        sizes: List[str], colors: List[str],
    ) -> Optional[str]:
        """Short, natural-sounding reply for a NARROW PRODUCT_INFO ask (giá
        and/or size/màu only - see intent_classifier.classify_product_focus).
        Deliberately a separate, much smaller call than
        format_product_deep_dive(): a bare "giá bao nhiêu" doesn't need a
        market analysis, just the requested field(s) worded naturally.
        Returns None on any failure so the caller (response_formatter's
        DETAIL_FOCUS branch) falls back to a plain deterministic line."""
        facts = []
        if focus.get("price"):
            facts.append(f"Giá: {price:,.0f}đ" if price is not None else "Giá: chưa rõ")
            facts.append(f"Tình trạng kho: {'còn hàng' if (stock or 0) > 0 else 'hết hàng'}")
        if focus.get("variant"):
            facts.append(f"Kích cỡ có sẵn: {', '.join(sizes) if sizes else 'chưa có thông tin size cụ thể'}")
            facts.append(f"Màu sắc có sẵn: {', '.join(colors) if colors else 'chưa có thông tin màu cụ thể'}")
        if not facts:
            return None
        template = load_prompt_template("product_focus_prompt.txt")
        prompt = template.format(
            product_name=product_name,
            facts="\n".join(f"- {f}" for f in facts),
        )
        if not llm_provider.is_available():
            return None
        try:
            result = await llm_provider.generate_text(prompt=prompt, model_tier="product_focus")
            log_usage("Product Focus Reply", result.prompt_tokens, result.completion_tokens)
            return result.value
        except Exception as e:
            print(f"\n[{llm_provider.name} - Error in Product Focus Reply] {e}.\n")
            return None

    def get_embedding(
        self,
        text: str,
        task_type: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        if not text:
            return []

        # 1. Try local Nomic embedding first
        try:
            return _nomic_embed(text, task_type)
        except Exception as e:
            print(f"\n[Embedding - Error in Local Nomic] {e}. Falling back to API providers...\n")

        # 2. Try active provider's embedding
        try:
            vector = llm_provider.embed(text, task_type=task_type, output_dimensionality=output_dimensionality)
            if vector:
                return vector
        except Exception:
            pass

        # 3. Fallback to Gemini if active provider failed or doesn't support embedding
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
