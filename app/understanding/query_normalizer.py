import re
from app.knowledge.ontology import ontology

class QueryNormalizer:
    def normalize(self, query: str) -> str:
        if not query:
            return ""
        # Remove multiple spaces, make lower
        text = re.sub(r"\s+", " ", query.lower()).strip()
        
        # Tokenize and normalize each word/phrase
        words = text.split(" ")
        normalized_words = []
        for word in words:
            norm = ontology.normalize_term(word)
            normalized_words.append(norm)
            
        return " ".join(normalized_words)

query_normalizer = QueryNormalizer()
