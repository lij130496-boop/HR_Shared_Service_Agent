from __future__ import annotations

from pathlib import Path
from .document_loader import iter_supported_files, load_file
from .chunker import chunk_blocks
from .embeddings import EmbeddingClient
from .vector_store import LocalVectorStore


def build_index(
    knowledge_dir: Path,
    vector_store: LocalVectorStore,
    embedder: EmbeddingClient,
) -> dict:
    files = list(iter_supported_files(knowledge_dir))
    if not files:
        raise RuntimeError(f"知识库目录为空: {knowledge_dir}")

    all_chunks = []
    for path in files:
        blocks = load_file(path)
        chunks = chunk_blocks(blocks)
        all_chunks.extend(chunks)

    if not all_chunks:
        raise RuntimeError("未从知识文件中解析出有效文本。")

    texts = [c.text for c in all_chunks]
    vectors = embedder.embed_texts(texts)

    metadata = [c.to_dict() for c in all_chunks]
    vector_store.save(vectors, metadata)

    return {
        "file_count": len(files),
        "chunk_count": len(all_chunks),
        "files": [p.name for p in files],
    }
