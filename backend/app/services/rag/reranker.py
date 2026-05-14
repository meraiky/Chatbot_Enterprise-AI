from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

class Reranker:
    """
    Reranks retrieved documents to improve precision.
    In a full production setup, this would use a Cross-Encoder model 
    (e.g., from sentence-transformers) to score the (query, document) pair.
    """
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model = None
        self._load_error = None
        
    def _load_model(self):
        """Lazy load the Cross-Encoder model."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name)
            except ImportError:
                self._load_error = "sentence-transformers not installed"
                logger.warning("sentence-transformers not installed. Falling back to simple reranking.")
                self._model = None
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"Failed to load Cross-Encoder model {self.model_name}: {e}")
                self._model = None

    def rerank(self, query: str, documents: List[str], scores: List[float] = None) -> List[Tuple[str, float]]:
        """
        Reranks documents based on the query.
        Returns a list of (document, new_score) sorted by score descending.
        """
        if not documents:
            return []

        self._load_model()

        if self._model is None:
            # Fallback: Return original order if no model is available
            # If scores are provided, use them; otherwise, assume 1.0
            fallback_scores = scores if scores else [1.0] * len(documents)
            return sorted(zip(documents, fallback_scores), key=lambda x: x[1], reverse=True)

        # Cross-Encoder expects pairs of (query, doc)
        pairs = [[query, doc] for doc in documents]
        new_scores = self._model.predict(pairs)
        
        return sorted(zip(documents, new_scores), key=lambda x: x[1], reverse=True)

    def health(self) -> dict:
        self._load_model()
        return {
            "available": self._model is not None,
            "model": self.model_name if self._model is not None else None,
            "status": "ok" if self._model is not None else "fallback_to_original_order",
            "error": self._load_error,
        }

# Singleton instance
reranker = Reranker()
