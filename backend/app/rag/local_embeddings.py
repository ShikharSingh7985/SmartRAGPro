from langchain_core.embeddings import Embeddings

from backend.app.core.config import Settings


class LocalEmbeddings(Embeddings):
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(settings.local_embedding_model, device="cpu")
        if self.model.get_sentence_embedding_dimension() != settings.embedding_dimensions:
            raise ValueError("Local model dimension differs from configured vector dimension")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
