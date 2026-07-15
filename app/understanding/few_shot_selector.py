import json
import os
from typing import Any, Dict, List, Optional

from app.client.llm_client import llm_client_wrapper
from app.database.conversation_repository import cosine_similarity

_EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "parser_examples.json")

# How many similarity-selected examples to add on top of the fixed anchors
# (see _load_examples' own note) - tunable without touching the examples
# data or the selection logic itself.
_DYNAMIC_K = 2

_examples: Optional[List[Dict[str, Any]]] = None
_pool_embeddings: Optional[List[List[float]]] = None

def _load_examples() -> List[Dict[str, Any]]:
    global _examples
    if _examples is None:
        with open(_EXAMPLES_PATH, "r", encoding="utf-8") as f:
            _examples = json.load(f)
    return _examples

def _pool() -> List[Dict[str, Any]]:
    return [ex for ex in _load_examples() if not ex.get("anchor")]

def _anchors() -> List[Dict[str, Any]]:
    return [ex for ex in _load_examples() if ex.get("anchor")]

def _get_pool_embeddings() -> List[List[float]]:
    """Embeddings for the POOL examples only (anchors are always included
    regardless of similarity, so never need embedding) - computed ONCE per
    process via the local Nomic model (see llm_client.get_embedding, tried
    local-first) and cached in memory, since these 13ish example strings are
    static for the process lifetime. A per-request embedding call would
    defeat the whole point of this optimization."""
    global _pool_embeddings
    if _pool_embeddings is None:
        _pool_embeddings = [llm_client_wrapper.get_embedding(ex["query"]) for ex in _pool()]
    return _pool_embeddings

def _render_example(ex: Dict[str, Any]) -> str:
    lines = [f'Query: "{ex["query"]}"']
    lines.extend(ex.get("context") or [])
    lines.append(f'Output: {json.dumps(ex["output"], ensure_ascii=False)}')
    return "\n".join(lines)

def select_examples(message_vector: Optional[List[float]]) -> str:
    """Renders the few-shot block for parser_prompt.txt's {examples}
    placeholder - a fixed ANCHOR set (one example per major decision
    boundary: SEARCH none/assist/expert, SOCIAL compliment/no_intent,
    PRODUCT_INFO confirm, COMPARE by position, CHITCHAT-vs-SEARCH) always
    included, PLUS the _DYNAMIC_K pool examples most similar to THIS
    message (by cosine similarity over the same local Nomic embedding
    already computed for the semantic parse cache - see
    orchestrator.py/parser.py's query_vector_lazy, reused here for free).

    Cuts parser_prompt.txt's fixed few-shot cost from ~3,900 tokens (all 23
    examples, every turn) to ~1,000-1,100 (7 anchors + 2 dynamic), while the
    anchor set keeps the model from losing coverage of the boundaries that
    are genuinely hard for embedding similarity alone to generalize (a bare
    "ok" vs "có" confirming a pending question - same text, different
    history; "tìm hiểu về X" reading as CHITCHAT not SEARCH; position-based
    COMPARE). Boundaries that are either more prototypical (an explicit
    "iPhone 16 128GB"-style query, a plain "cảm ơn") or redundant with
    another anchor (a second purpose-reply domain) were demoted to
    "anchor": false rather than deleted - they stay in the pool for dynamic
    selection AND in try_embedding_fastpath's matching corpus (see below),
    just without the guarantee of always being included. If `message_vector`
    is unavailable (embedding failed), only the anchors are used - still the
    hard-boundary coverage, just without the topic-specific extras."""
    anchors = _anchors()
    selected = list(anchors)

    if message_vector:
        pool = _pool()
        embeddings = _get_pool_embeddings()
        scored = [
            (cosine_similarity(message_vector, emb) if emb else 0.0, ex)
            for ex, emb in zip(pool, embeddings)
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected += [ex for _, ex in scored[:_DYNAMIC_K]]

    return "\n\n".join(_render_example(ex) for ex in selected)


_all_embeddings: Optional[List[List[float]]] = None

def _get_all_embeddings() -> List[List[float]]:
    global _all_embeddings
    if _all_embeddings is None:
        examples = _load_examples()
        _all_embeddings = [llm_client_wrapper.get_embedding(ex["query"]) for ex in examples]
    return _all_embeddings

def try_embedding_fastpath(
    message_vector: Optional[List[float]],
    threshold: float = 0.86,
    margin: float = 0.1
) -> Optional[Any]:
    """Checks if the query vector matches a safe CHITCHAT/SOCIAL example with high
    confidence, allowing us to bypass the LLM entirely.
    """
    if not message_vector:
        return None
        
    examples = _load_examples()
    embeddings = _get_all_embeddings()
    
    # Exclude history-dependent or reference-based examples
    excluded_ids = {"bare_ok_no_pending_question", "bare_co_confirms_pending_question", "compare_by_position"}
    
    scored = []
    for ex, emb in zip(examples, embeddings):
        if not emb:
            continue
        sim = cosine_similarity(message_vector, emb)
        scored.append((sim, ex))
        
    if not scored:
        return None
        
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best_ex = scored[0]
    
    output = best_ex.get("output") or {}
    best_intent = output.get("intent")
    
    if best_intent not in ("CHITCHAT", "SOCIAL") or best_ex.get("id") in excluded_ids:
        return None
        
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    
    if best_score >= threshold and (best_score - second_score) >= margin:
        print(f"\n[Fast-Path] Query matched '{best_ex.get('query')}' (id: {best_ex.get('id')}) "
              f"with score {best_score:.4f} (second: {second_score:.4f}). Bypassing AI Parser.")
              
        from app.models.shopping_context import ShoppingContext
        return ShoppingContext(
            intent=output.get("intent"),
            sub_intent=output.get("sub_intent"),
            category=output.get("category"),
            brand=output.get("brand"),
            price_min=output.get("price_min"),
            price_max=output.get("price_max"),
            purpose=output.get("purpose"),
            compare_targets=output.get("compare_targets") or [],
            product=output.get("product"),
            query_q=output.get("query_q"),
            expanded_queries=output.get("expanded_queries") or []
        )
        
    return None

