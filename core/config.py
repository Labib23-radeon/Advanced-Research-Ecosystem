"""Configuration management for the Local Research Agent."""
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    """Global configuration settings for local offline research agent."""

    # Ollama Local LLM Configuration
    ollama_host: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
        description="Local Ollama server URL (e.g. http://127.0.0.1:11434)",
    )
    ollama_model: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        description="Default local Ollama model to use (e.g., llama3.2:3b, qwen2.5:7b, mistral)",
    )
    request_timeout: float = Field(
        default_factory=lambda: float(os.getenv("OLLAMA_TIMEOUT", "120.0")),
        description="Timeout in seconds for Ollama requests",
    )

    # Embedding & Vector Database
    embedding_model_name: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        description="SentenceTransformer embedding model name for ChromaDB",
    )
    chroma_collection_name: str = Field(
        default="local_research_memory",
        description="Default Chroma collection name",
    )

    # Agent Loop Parameters
    max_research_steps: int = Field(
        default=8,
        description="Maximum ReAct iterations before forcing synthesis",
    )
    max_search_results: int = Field(
        default=5,
        description="Number of search results to fetch per web search",
    )
    scrape_timeout: int = Field(
        default=4,
        description="Timeout in seconds for scraping individual web pages",
    )
    max_content_length: int = Field(
        default=3500,
        description="Max character length for scraped webpage text passed to LLM",
    )
    chunk_size: int = Field(
        default=600,
        description="Document chunk size in characters for vector storage",
    )
    chunk_overlap: int = Field(
        default=100,
        description="Overlap between document chunks in characters",
    )

    # File System Paths
    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data"
    )
    output_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "outputs"
    )
    chroma_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "chroma_db"
    )
    uploads_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "uploads"
    )

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not already exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = AgentSettings()
settings.ensure_directories()
