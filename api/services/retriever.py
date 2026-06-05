import os
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery, QueryType
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class RetrievedChunk:
    content: str
    source_file: str
    page_number: int
    section: str
    title: str
    score: float


class Retriever:
    def __init__(self, credential: DefaultAzureCredential):
        self.search_client = SearchClient(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            index_name="notebooklm-chunks",
            credential=credential,
        )

        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        self.openai_client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )
        self.embedding_model = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get_query_embedding(self, query: str) -> list[float]:
        response = self.openai_client.embeddings.create(
            input=query,
            model=self.embedding_model,
            dimensions=3072,
        )
        return response.data[0].embedding

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        query_embedding = self._get_query_embedding(query)

        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k * 3,
            fields="content_vector",
        )

        results = self.search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name="default-semantic-config",
            top=top_k,
            select=["id", "content", "source_file", "page_number", "section", "title", "chunk_index"],
        )

        chunks = []
        for r in results:
            chunks.append(
                RetrievedChunk(
                    content=r["content"],
                    source_file=r["source_file"],
                    page_number=r.get("page_number", 1),
                    section=r.get("section", ""),
                    title=r.get("title", ""),
                    score=r.get("@search.reranker_score") or r.get("@search.score", 0.0),
                )
            )

        return chunks
