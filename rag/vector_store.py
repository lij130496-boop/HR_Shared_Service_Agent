from __future__ import annotations

import json
from pathlib import Path
import numpy as np


class LocalVectorStore:
    def __init__(self, vector_path: Path, metadata_path: Path):
        self.vector_path = vector_path
        self.metadata_path = metadata_path
        self.vectors: np.ndarray | None = None
        self.metadata: list[dict] = []

    @property
    def exists(self) -> bool:
        return self.vector_path.exists() and self.metadata_path.exists()

    def save(self, vectors: np.ndarray, metadata: list[dict]) -> None:
        self.vector_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.vector_path, vectors=vectors)
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.vectors = vectors
        self.metadata = metadata

    def load(self) -> None:
        if not self.exists:
            raise FileNotFoundError("向量索引不存在，请先构建知识库索引。")
        self.vectors = np.load(self.vector_path)["vectors"].astype(np.float32)
        self.metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[dict]:
        if self.vectors is None:
            self.load()

        if len(self.metadata) == 0:
            return []

        scores = self.vectors @ query_vector
        top_idx = np.argsort(scores)[::-1][:top_k]

        results: list[dict] = []
        for idx in top_idx:
            item = dict(self.metadata[int(idx)])
            item["score"] = float(scores[int(idx)])
            results.append(item)
        return results
