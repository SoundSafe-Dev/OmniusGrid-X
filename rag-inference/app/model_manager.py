"""
Model manager for the rag-inference service.

Loads BGE-M3 (dual-mode embeddings) and BGE-Reranker-v2-m3 (cross-encoder) via
BAAI's ``FlagEmbedding`` library - the reference implementation, which returns
dense + sparse in a single pass. CPU-first: fp16 is auto-disabled when no CUDA
device is present (fp16 on CPU is unsupported/slow), and enabled automatically
on GPU. No code change to move between CPU and GPU - just the hardware.
"""

import os
from typing import List, Dict, Tuple

import structlog

logger = structlog.get_logger()


class ModelManager:
    def __init__(self) -> None:
        self.embedding_model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.reranker_model_name = os.getenv(
            "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
        )
        # Resolve device/fp16 from hardware. fp16 only makes sense on CUDA.
        self._cuda = self._detect_cuda()
        want_fp16 = os.getenv("USE_FP16", "true").lower() == "true"
        self.use_fp16 = want_fp16 and self._cuda
        self.device_str = "cuda" if self._cuda else "cpu"

        self._embedder = None
        self._reranker = None

    @staticmethod
    def _detect_cuda() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except Exception:
            return False

    @property
    def loaded(self) -> bool:
        return self._embedder is not None and self._reranker is not None

    def load(self) -> None:
        """Load both models (blocking; called once at startup)."""
        from FlagEmbedding import BGEM3FlagModel, FlagReranker

        logger.info(
            "loading_embedder",
            model=self.embedding_model_name,
            device=self.device_str,
            fp16=self.use_fp16,
        )
        self._embedder = BGEM3FlagModel(
            self.embedding_model_name, use_fp16=self.use_fp16
        )
        logger.info(
            "loading_reranker",
            model=self.reranker_model_name,
            device=self.device_str,
            fp16=self.use_fp16,
        )
        self._reranker = FlagReranker(
            self.reranker_model_name, use_fp16=self.use_fp16
        )
        logger.info("models_loaded")

    def embed(
        self, texts: List[str], is_query: bool
    ) -> Tuple[List[List[float]], List[Dict[str, List]]]:
        """Return (dense_vectors, sparse_vectors) for the given texts.

        Sparse vectors are converted from BGE-M3's ``{token_id: weight}`` dict
        into Qdrant-native ``{"indices": [...], "values": [...]}``.
        """
        encode = (
            self._embedder.encode_queries if is_query else self._embedder.encode_corpus
        )
        output = encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = [vec.tolist() for vec in output["dense_vecs"]]
        sparse: List[Dict[str, List]] = []
        for weights in output["lexical_weights"]:
            sparse.append(
                {
                    "indices": [int(token_id) for token_id in weights.keys()],
                    "values": [float(weight) for weight in weights.values()],
                }
            )
        return dense, sparse

    def rerank(self, query: str, passages: List[str]) -> List[float]:
        """Cross-encoder scores (0-1) for each passage, in input order."""
        if not passages:
            return []
        pairs = [[query, passage] for passage in passages]
        scores = self._reranker.compute_score(pairs, normalize=True)
        # compute_score returns a float for a single pair, else a list.
        if isinstance(scores, (int, float)):
            scores = [scores]
        return [float(score) for score in scores]
