"""Thread-safe local vector database integration with ChromaDB and atomic embedded fallback."""
import hashlib
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.config import settings

logger = logging.getLogger(__name__)


class LightweightVectorStore:
    """Zero-dependency thread-safe persistent BM25 store with atomic disk snapshots."""

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self.persist_path = persist_path or (settings.data_dir / "local_memory.json")
        self._lock = threading.RLock()
        self.documents: List[Dict[str, Any]] = []
        self.inverted_index: Dict[str, Set[int]] = {}
        self._load()

    def _build_inverted_index(self) -> None:
        self.inverted_index = {}
        for idx, doc in enumerate(self.documents):
            for token in doc.get("tf", {}).keys():
                if token not in self.inverted_index:
                    self.inverted_index[token] = set()
                self.inverted_index[token].add(idx)

    def _load(self) -> None:
        with self._lock:
            if self.persist_path.exists():
                try:
                    data = json.loads(self.persist_path.read_text(encoding="utf-8"))
                    self.documents = data.get("documents", [])
                    self._build_inverted_index()
                except Exception as exc:
                    logger.warning("Could not read local memory file: %s", exc)
                    self.documents = []
                    self.inverted_index = {}

    def _save(self) -> None:
        with self._lock:
            try:
                self.persist_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.persist_path.with_suffix(".json.tmp")
                tmp_path.write_text(
                    json.dumps({"documents": self.documents}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp_path.replace(self.persist_path)
            except Exception as exc:
                logger.warning("Could not persist local memory: %s", exc)

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        with self._lock:
            count_added = 0
            now_ts = time.time()
            for idx, text in enumerate(texts):
                clean_text = text.strip()
                if not clean_text:
                    continue

                doc_id = (
                    ids[idx]
                    if ids and idx < len(ids)
                    else hashlib.sha256(f"{clean_text}_{idx}_{now_ts}".encode("utf-8")).hexdigest()[:16]
                )
                meta = metadatas[idx] if metadatas and idx < len(metadatas) else {}
                meta["timestamp"] = meta.get("timestamp", now_ts)

                tokens = self._tokenize(clean_text)
                tf: Dict[str, float] = {}
                for t in tokens:
                    tf[t] = tf.get(t, 0.0) + 1.0

                doc_idx = len(self.documents)
                self.documents.append({
                    "id": doc_id,
                    "text": clean_text,
                    "metadata": meta,
                    "tf": tf,
                    "length": len(tokens),
                })
                for token in tf.keys():
                    if token not in self.inverted_index:
                        self.inverted_index[token] = set()
                    self.inverted_index[token].add(doc_idx)
                count_added += 1

            self._save()
            return count_added

    def upsert_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        """Insert or update documents by ID."""
        if not ids:
            return self.add_texts(texts, metadatas=metadatas, ids=ids)

        with self._lock:
            existing_map = {doc.get("id"): idx for idx, doc in enumerate(self.documents) if doc.get("id")}
            to_add_texts: List[str] = []
            to_add_metas: List[Dict[str, Any]] = []
            to_add_ids: List[str] = []
            updated = 0
            now_ts = time.time()

            for idx, text in enumerate(texts):
                clean_text = text.strip()
                if not clean_text:
                    continue
                doc_id = (
                    ids[idx]
                    if idx < len(ids)
                    else hashlib.sha256(f"{clean_text}_{idx}_{now_ts}".encode("utf-8")).hexdigest()[:16]
                )
                meta = metadatas[idx] if metadatas and idx < len(metadatas) else {}
                meta["timestamp"] = meta.get("timestamp", now_ts)

                if doc_id in existing_map:
                    pos = existing_map[doc_id]
                    tokens = self._tokenize(clean_text)
                    tf: Dict[str, float] = {}
                    for t in tokens:
                        tf[t] = tf.get(t, 0.0) + 1.0
                    self.documents[pos] = {
                        "id": doc_id,
                        "text": clean_text,
                        "metadata": meta,
                        "tf": tf,
                        "length": len(tokens),
                    }
                    updated += 1
                else:
                    to_add_texts.append(clean_text)
                    to_add_metas.append(meta)
                    to_add_ids.append(doc_id)

            if updated:
                self._build_inverted_index()
                self._save()

            added = self.add_texts(to_add_texts, metadatas=to_add_metas, ids=to_add_ids) if to_add_texts else 0
            return updated + added

    def query(self, query_text: str, n_results: int = 4) -> List[Dict[str, Any]]:
        with self._lock:
            query_tokens = self._tokenize(query_text)
            if not query_tokens or not self.documents:
                return []

            candidate_indices: Set[int] = set()
            df: Dict[str, int] = {}
            for token in query_tokens:
                posting = self.inverted_index.get(token, set())
                df[token] = len(posting)
                candidate_indices.update(posting)

            if not candidate_indices:
                return []

            total_docs = len(self.documents)
            scored: List[Tuple[float, Dict[str, Any]]] = []

            for doc_idx in candidate_indices:
                doc = self.documents[doc_idx]
                doc_tf = doc.get("tf", {})
                score = 0.0
                for token in query_tokens:
                    if token in doc_tf:
                        idf = math.log((total_docs - df[token] + 0.5) / (df[token] + 0.5) + 1.0)
                        tf_val = doc_tf[token]
                        score += idf * (tf_val / (tf_val + 1.5))

                if score > 0.0:
                    scored.append((score, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "text": doc["text"],
                    "metadata": doc.get("metadata", {}),
                    "distance": 1.0 / (1.0 + score),
                }
                for score, doc in scored[:n_results]
            ]

    def count(self) -> int:
        with self._lock:
            return len(self.documents)

    def clear(self) -> None:
        with self._lock:
            self.documents = []
            self.inverted_index = {}
            self._save()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower())


class LocalVectorStore:
    """Thread-safe ChromaDB vector store with automatic atomic LightweightVectorStore fallback."""

    def __init__(
        self,
        collection_name: Optional[str] = None,
        persist_dir: Optional[str] = None,
        embedding_model_name: Optional[str] = None,
    ) -> None:
        self.persist_dir = str(persist_dir or settings.chroma_dir)
        self.collection_name = collection_name or settings.chroma_collection_name
        self.model_name = embedding_model_name or settings.embedding_model_name
        self._lock = threading.RLock()
        self.use_chroma = False
        self.chroma_client = None
        self.collection = None
        self.fallback_store = LightweightVectorStore(
            persist_path=Path(self.persist_dir) / f"{self.collection_name}.json"
        )

        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from chromadb.utils import embedding_functions

            self.chroma_client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
            )
            try:
                self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=self.model_name
                )
            except Exception:
                self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()

            self.collection = self.chroma_client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
            )
            self.use_chroma = True
        except Exception as exc:
            logger.info("Using embedded lightweight local vector store: %s", exc)
            self.use_chroma = False

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        with self._lock:
            if self.use_chroma and self.collection is not None:
                try:
                    valid_texts: List[str] = []
                    valid_metas: List[Dict[str, Any]] = []
                    valid_ids: List[str] = []
                    now_ts = time.time()

                    for idx, text in enumerate(texts):
                        ct = text.strip()
                        if not ct:
                            continue
                        doc_id = (
                            ids[idx]
                            if ids and idx < len(ids)
                            else hashlib.sha256(f"{ct}_{idx}_{now_ts}".encode("utf-8")).hexdigest()[:16]
                        )
                        raw_meta = metadatas[idx] if metadatas and idx < len(metadatas) else {}
                        clean_meta = {
                            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                            for k, v in raw_meta.items()
                        }
                        clean_meta["timestamp"] = clean_meta.get("timestamp", now_ts)

                        valid_texts.append(ct)
                        valid_metas.append(clean_meta)
                        valid_ids.append(doc_id)

                    if valid_texts:
                        self.collection.add(documents=valid_texts, metadatas=valid_metas, ids=valid_ids)
                        return len(valid_texts)
                except Exception as exc:
                    logger.warning("Chroma add_texts failed, falling back: %s", exc)

            return self.fallback_store.add_texts(texts, metadatas=metadatas, ids=ids)

    def upsert_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        """Insert or update texts in ChromaDB or fallback LightweightVectorStore."""
        with self._lock:
            if self.use_chroma and self.collection is not None:
                try:
                    valid_texts: List[str] = []
                    valid_metas: List[Dict[str, Any]] = []
                    valid_ids: List[str] = []
                    now_ts = time.time()

                    for idx, text in enumerate(texts):
                        ct = text.strip()
                        if not ct:
                            continue
                        doc_id = (
                            ids[idx]
                            if ids and idx < len(ids)
                            else hashlib.sha256(f"{ct}_{idx}_{now_ts}".encode("utf-8")).hexdigest()[:16]
                        )
                        raw_meta = metadatas[idx] if metadatas and idx < len(metadatas) else {}
                        clean_meta = {
                            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                            for k, v in raw_meta.items()
                        }
                        clean_meta["timestamp"] = clean_meta.get("timestamp", now_ts)

                        valid_texts.append(ct)
                        valid_metas.append(clean_meta)
                        valid_ids.append(doc_id)

                    if valid_texts:
                        self.collection.upsert(documents=valid_texts, metadatas=valid_metas, ids=valid_ids)
                        return len(valid_texts)
                except Exception as exc:
                    logger.warning("Chroma upsert_texts failed, falling back: %s", exc)

            return self.fallback_store.upsert_texts(texts, metadatas=metadatas, ids=ids)

    def add_scraped_document(self, url: str, title: str, text: str) -> int:
        chunks = self._chunk_string(text, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
        metadatas = [
            {
                "source_type": "webpage",
                "source": url,
                "title": title,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]
        return self.add_texts(chunks, metadatas=metadatas)

    def add_pdf_chunks(self, pdf_chunks: List[Dict[str, Any]]) -> int:
        texts = [chunk["text"] for chunk in pdf_chunks]
        metadatas = [
            {
                "source_type": chunk.get("metadata", {}).get("doc_type", "pdf"),
                **chunk.get("metadata", {}),
            }
            for chunk in pdf_chunks
        ]
        return self.add_texts(texts, metadatas=metadatas)

    def query(
        self,
        query_text: str,
        n_results: int = 4,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            if self.use_chroma and self.collection is not None:
                try:
                    count = self.collection.count()
                    if count > 0:
                        actual_n = min(n_results, count)
                        res = self.collection.query(query_texts=[query_text], n_results=actual_n, where=where)
                        if res and "documents" in res and res["documents"]:
                            docs = res["documents"][0]
                            metas = res.get("metadatas", [[]])[0]
                            distances = res.get("distances", [[]])[0] if "distances" in res and res["distances"] else []
                            return [
                                {
                                    "text": docs[i],
                                    "metadata": metas[i] if i < len(metas) else {},
                                    "distance": distances[i] if i < len(distances) else None,
                                }
                                for i in range(len(docs))
                            ]
                except Exception as exc:
                    logger.warning("Chroma query failed, falling back: %s", exc)

            return self.fallback_store.query(query_text, n_results=n_results)

    def query_formatted(self, query_text: str, n_results: int = 4) -> str:
        results = self.query(query_text, n_results=n_results)
        if not results:
            return f"No relevant local memory chunks found for: '{query_text}'."

        output = [f"### Relevant Knowledge from Local Vector Store for: '{query_text}'"]
        for idx, item in enumerate(results, 1):
            meta = item.get("metadata", {})
            source = meta.get("source", "Unknown Source")
            page_info = f" (Page {meta['page']})" if "page" in meta else ""
            title_info = f" - {meta['title']}" if "title" in meta else ""
            output.append(
                f"[{idx}] Source: {source}{page_info}{title_info}\n"
                f"    {item['text']}"
            )
        return "\n\n".join(output)

    def count(self) -> int:
        with self._lock:
            if self.use_chroma and self.collection is not None:
                try:
                    return self.collection.count()
                except Exception:
                    pass
            return self.fallback_store.count()

    def clear(self) -> None:
        with self._lock:
            if self.use_chroma and self.collection is not None:
                try:
                    self.chroma_client.delete_collection(self.collection_name)
                    self.collection = self.chroma_client.get_or_create_collection(
                        name=self.collection_name,
                        embedding_function=self.embedding_fn,
                    )
                except Exception:
                    pass
            self.fallback_store.clear()

    def _chunk_string(self, text: str, chunk_size: int = 600, overlap: int = 100) -> List[str]:
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if end < len(text):
                last_space = chunk.rfind(" ")
                if last_space > int(chunk_size * 0.5):
                    chunk = chunk[:last_space]
                    start += last_space + 1
                else:
                    start += chunk_size - overlap
            else:
                start += chunk_size
            c = chunk.strip()
            if c:
                chunks.append(c)
        return chunks
