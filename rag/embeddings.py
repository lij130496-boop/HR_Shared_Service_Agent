
from __future__ import annotations

import numpy as np
from openai import OpenAI


class EmbeddingClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise RuntimeError(
                "未找到 DASHSCOPE_API_KEY。"
                "请确认 BailianTest/.env 或当前项目 .env 中已配置该变量。"
            )

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

    def embed_texts(self, texts: list[str], batch_size: int = 10) -> np.ndarray:
        """
        百炼 text-embedding-v4 批量调用。
        按 10 条一批，避免超过常见批量限制。
        """
        vectors: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            resp = self.client.embeddings.create(
                model=self.model,
                input=batch,
                encoding_format="float",
            )

            # 按 index 排序，确保向量顺序与输入顺序一致
            ordered = sorted(resp.data, key=lambda x: x.index)
            vectors.extend(item.embedding for item in ordered)

        arr = np.asarray(vectors, dtype=np.float32)
        return self._normalize(arr)

    def embed_query(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(
            model=self.model,
            input=[text],
            encoding_format="float",
        )

        arr = np.asarray(resp.data[0].embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return arr if norm == 0 else arr / norm

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
