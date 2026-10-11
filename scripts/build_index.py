from config import settings
from rag.embeddings import EmbeddingClient
from rag.vector_store import LocalVectorStore
from rag.indexer import build_index


def main():
    embedder = EmbeddingClient(settings.api_key, settings.base_url, settings.embedding_model)
    store = LocalVectorStore(settings.vector_store_path, settings.metadata_path)
    result = build_index(settings.knowledge_dir, store, embedder)
    print("索引构建完成")
    print(result)


if __name__ == "__main__":
    main()
