from __future__ import annotations

from .embeddings import EmbeddingClient
from .vector_store import LocalVectorStore


class Retriever:
    def __init__(self, embedder: EmbeddingClient, store: LocalVectorStore, top_k: int = 5):
        self.embedder = embedder
        self.store = store
        self.top_k = top_k

    def retrieve(self, query: str) -> list[dict]:
        q = self.embedder.embed_query(query)
        return self.store.search(q, self.top_k)
