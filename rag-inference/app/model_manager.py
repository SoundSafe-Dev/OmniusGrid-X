"""
Model manager for the rag-inference service.

Embeddings use BGE-M3 via BAAI's ``FlagEmbedding`` (``BGEM3FlagModel``) - the
reference implementation, which returns dense + sparse in a single pass.

Reranking uses ``bge-reranker-v2-m3`` directly through ``transformers``
(``AutoModelForSequenceClassification``) rather than FlagEmbedding's
``FlagReranker``: the latter calls ``tokenizer.prepare_for_model``, a path
removed from current ``transformers``, which crashes on the slow tokenizer. The
raw cross-encoder API (tokenize pairs -> logits -> sigmoid) is the usage shown on
the model card and is stable across ``transformers`` versions - so we can keep
``transformers`` recent enough for the embedder without breaking the reranker.

CPU-first: fp16 is auto-disabled when no CUDA device is present (fp16 on CPU is
unsupported/slow), and enabled automatically on GPU. No code change to move
between CPU and GPU - just the hardware.
"""

import os
from typing import List, Dict, Tuple

import structlog

logger = structlog.get_logger()

# Truncation length for (query, passage) pairs fed to the cross-encoder.
_RERANK_MAX_LENGTH = 512


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
        self._reranker_tokenizer = None
        self._reranker_model = None

    @staticmethod
    def _detect_cuda() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except Exception:
            return False

    @property
    def loaded(self) -> bool:
        return self._embedder is not None and self._reranker_model is not None

    def load(self) -> None:
        """Load both models (blocking; called once at startup)."""
        from FlagEmbedding import BGEM3FlagModel
        from transformers import (
            AutoTokenizer,
            AutoModelForSequenceClassification,
        )

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
        self._reranker_tokenizer = AutoTokenizer.from_pretrained(
            self.reranker_model_name
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self.reranker_model_name
        )
        if self.use_fp16:  # only true on CUDA (see __init__)
            model = model.half()
        model = model.to(self.device_str)
        model.eval()
        self._reranker_model = model

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
        """Cross-encoder relevance scores (0-1) for each passage, input order.

        Scores each ``(query, passage)`` pair jointly and squashes the logit
        through a sigmoid so results are comparable in [0, 1] - matching the
        ``normalize=True`` behavior callers previously relied on.
        """
        if not passages:
            return []
        import torch

        pairs = [[query, passage] for passage in passages]
        with torch.no_grad():
            inputs = self._reranker_tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=_RERANK_MAX_LENGTH,
            )
            inputs = {k: v.to(self.device_str) for k, v in inputs.items()}
            logits = self._reranker_model(**inputs, return_dict=True).logits
            scores = torch.sigmoid(logits.view(-1).float())
            return scores.cpu().tolist()
