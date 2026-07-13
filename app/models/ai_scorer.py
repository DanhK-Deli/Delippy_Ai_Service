from pydantic import BaseModel
from typing import List, Literal

class AIScoreReason(BaseModel):
    status: Literal["success", "warning"]
    text: str

class AIScoredProduct(BaseModel):
    """One product's suitability verdict from the Tier B long-tail AI Scorer
    (see recommendation_builder.py) - deliberately the SAME shape
    (suitability_score/recommend_reasons) Tier A's guide_rule.json scoring
    already produces, so response_formatter's star/bullet rendering works
    unchanged regardless of which tier scored a product."""
    slug: str
    suitability_score: int
    recommend_reasons: List[AIScoreReason]

class AIScorerResponse(BaseModel):
    products: List[AIScoredProduct]
