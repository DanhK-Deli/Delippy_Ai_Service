# Atlas Vector Search index for `product_embeddings`

Backs semantic product retrieval (`app/database/product_vector_repository.py`,
consumed by `app/retrieval/search_engine.py`). One index, on the
`product_embeddings` collection in the `delippy_ai` Atlas database (same
cluster as `MONGO_CORE_URI`).

## Definition

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine" },
    { "type": "filter", "path": "category_id" },
    { "type": "filter", "path": "subcategory_id" }
  ]
}
```

- Index name: `product_vector_index` (see `VECTOR_INDEX_NAME` in `product_vector_repository.py`).
- Index type: `vectorSearch`.
- `numDimensions: 1536` must exactly match `settings.EMBEDDING_DIMENSION` (`app/core/config.py`,
  env `EMBEDDING_DIMENSION`) and whatever every document's `embedding` array
  actually contains. **If this ever changes, every product must be
  re-embedded (rerun `sync_products()`) AND the index recreated** - a
  dimension mismatch doesn't error cleanly, it just returns wrong/empty
  results.
- `filter` fields let `$vectorSearch` pre-filter by `category_id`/`subcategory_id`
  before ranking by similarity (see `ProductVectorRepository.vector_search()`).
  `price_at_sync` is deliberately NOT a filter field - it's stale by
  definition (synced once, product prices change), so price filtering
  happens post-fetch against the LIVE price from `search_provider.get_details()`,
  never pre-filtered here.

## How the dimension (1536) was chosen

`GEMINI_EMBEDDING_MODEL` (`models/gemini-embedding-2`) defaults to a
**3072**-dim output (confirmed empirically, not from docs). The model
supports Matryoshka truncation via `output_dimensionality` - 1536 keeps
storage/query cost down while remaining L2-normalized (confirmed norm
≈ 1.0), so cosine similarity behaves correctly. Confirm empirically again if
the model changes:

```python
from app.core.llm import llm_provider
vec = llm_provider.embed("test", output_dimensionality=1536)
print(len(vec))
```

## Creating the index

**Automated (preferred, already wired in)**: `pymongo` 4.9.1 (confirmed
installed, ≥4.7 required) supports creating Atlas Search indexes directly
from the driver - no manual Atlas UI step needed:

```python
from app.database.product_vector_repository import product_vector_repo
await product_vector_repo.ensure_vector_index()  # idempotent
```

This has already been run once against the dev Atlas cluster during this
session - `index_status()` confirmed `status: READY, queryable: True`
(builds in roughly a minute for a small collection; larger catalogs take
longer - poll `index_status()`/`list_search_indexes()` before relying on
`vector_search()` returning results).

**Manual fallback** (Atlas UI or `mongosh`, if the automated path is ever
unavailable - e.g. a restricted service-account role that can't manage
search indexes):

```js
db.product_embeddings.createSearchIndex(
  "product_vector_index",
  "vectorSearch",
  {
    fields: [
      { type: "vector", path: "embedding", numDimensions: 1536, similarity: "cosine" },
      { type: "filter", path: "category_id" },
      { type: "filter", path: "subcategory_id" }
    ]
  }
)
```

## Operational notes

- Re-running `sync_products()` does NOT touch the index - it only upserts/prunes
  documents. The index auto-updates as documents change (Atlas maintains it
  incrementally), no manual rebuild needed after a normal sync.
- If `EMBEDDING_DIMENSION` or the embedding model changes, the index must be
  dropped and recreated (`coll.drop_search_index(name)` then
  `ensure_vector_index()` again) AFTER re-syncing every product - an index
  with a stale `numDimensions` silently mismatches new vectors.
