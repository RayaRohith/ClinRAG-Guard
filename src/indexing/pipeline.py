"""
Indexes documents into ChromaDB with sentence-transformer embeddings.

This pipeline is held fixed across the study — it is not the variable
under test. It just provides a realistic RAG context for the detection
sources to operate in. Persistent ChromaDB, 512-word chunks with
64-word overlap, metadata stored alongside each chunk.
"""

import hashlib
import logging
import re
from pathlib import Path

from src.utils.config import to_relative, resolve_path
from typing import Optional
from xml.etree import ElementTree as ET

import chromadb
from sentence_transformers import SentenceTransformer

from src.utils.config import (
    EMBEDDING_MODEL, CHROMA_COLLECTION, INDEX_DIR,
    CHUNK_SIZE, CHUNK_OVERLAP,
)
from src.data.manifest import DataManifest, ManifestEntry, GroundTruthLabel

logger = logging.getLogger(__name__)


def extract_text_from_xml(xml_path: Path) -> str:
    """
    Extract plain text from Europe PMC JATS XML or DailyMed SPL XML.
    Handles both formats by stripping all tags and joining text content.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {xml_path}: {e}")
        return ""

    texts = []
    for elem in root.iter():
        if elem.text:
            texts.append(elem.text.strip())
        if elem.tail:
            texts.append(elem.tail.strip())

    raw = " ".join(t for t in texts if t)
    return re.sub(r"\s+", " ", raw).strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks by word count.

    Uses word-level splitting (approximating tokens) rather than
    character-level, since the embedding model tokenises by words/subwords.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap

    return chunks


class IndexingPipeline:
    """Indexes study corpus documents into ChromaDB for retrieval."""

    def __init__(self, persist_dir: str = None):
        self.persist_dir = Path(persist_dir) if persist_dir else INDEX_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = None

    def _get_or_create_collection(self, reset: bool = False):
        if reset:
            try:
                self.client.delete_collection(CHROMA_COLLECTION)
            except Exception:
                pass

        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        return self.collection

    def index_from_manifest(
        self,
        manifest: DataManifest,
        labels: Optional[list[GroundTruthLabel]] = None,
        reset: bool = True,
    ) -> dict:
        """
        Index documents listed in the manifest.

        Args:
            manifest: The data manifest with document entries.
            labels: Which ground-truth labels to index. Default indexes
                    RETRACTED, CONTROL, and OUTDATED (not CURRENT — the
                    newer drug label versions are ground truth, not corpus).
            reset: If True, wipe the collection before indexing.

        Returns:
            Stats dict with counts of documents and chunks indexed.
        """
        if labels is None:
            labels = [
                GroundTruthLabel.RETRACTED,
                GroundTruthLabel.CONTROL,
                GroundTruthLabel.OUTDATED,
            ]

        self._get_or_create_collection(reset=reset)

        entries = []
        for label in labels:
            entries.extend(manifest.get_by_label(label))

        logger.info(f"Indexing {len(entries)} documents (labels: {[l.value for l in labels]})")

        total_chunks = 0
        docs_indexed = 0
        docs_skipped = 0

        for entry in entries:
            path = resolve_path(entry.file_path)
            if not path.exists():
                logger.warning(f"File not found, skipping: {entry.doc_id} -> {path}")
                docs_skipped += 1
                continue

            text = extract_text_from_xml(path)
            if not text:
                logger.warning(f"No text extracted from {entry.doc_id}")
                docs_skipped += 1
                continue

            chunks = chunk_text(text)
            if not chunks:
                docs_skipped += 1
                continue

            ids = []
            documents = []
            metadatas = []
            for i, chunk in enumerate(chunks):
                chunk_id = f"{entry.doc_id}__chunk_{i}"
                ids.append(chunk_id)
                documents.append(chunk)
                metadatas.append({
                    "doc_id": entry.doc_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "source": entry.source.value,
                    "ground_truth": entry.ground_truth.value,
                    "title": entry.title or "",
                    "pmid": entry.pmid or "",
                    "doi": entry.doi or "",
                    "set_id": entry.set_id or "",
                })

            embeddings = self.embedder.encode(documents, show_progress_bar=False)

            self.collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings.tolist(),
                metadatas=metadatas,
            )

            total_chunks += len(chunks)
            docs_indexed += 1

            if docs_indexed % 50 == 0:
                logger.info(f"Indexed {docs_indexed} documents ({total_chunks} chunks)...")

        stats = {
            "documents_indexed": docs_indexed,
            "documents_skipped": docs_skipped,
            "total_chunks": total_chunks,
            "collection_size": self.collection.count(),
        }

        logger.info(
            f"Indexing complete: {docs_indexed} docs, {total_chunks} chunks, "
            f"{docs_skipped} skipped"
        )
        return stats

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        """
        Retrieve top-k chunks for a query.

        Returns list of dicts with keys: chunk_id, text, score, metadata.
        """
        if self.collection is None:
            self._get_or_create_collection(reset=False)

        if self.collection.count() == 0:
            logger.warning("Collection is empty — run index_from_manifest first")
            return []

        query_embedding = self.embedder.encode([query]).tolist()

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        retrieved = []
        for i in range(len(results["ids"][0])):
            retrieved.append({
                "chunk_id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "score": 1.0 - results["distances"][0][i],
                "metadata": results["metadatas"][0][i],
            })

        return retrieved

    def get_all_doc_ids(self) -> set[str]:
        """Return the set of unique document IDs in the index."""
        if self.collection is None:
            self._get_or_create_collection(reset=False)

        if self.collection.count() == 0:
            return set()

        all_meta = self.collection.get(include=["metadatas"])
        return {m["doc_id"] for m in all_meta["metadatas"]}

    def get_document_chunks(self, doc_id: str) -> list[dict]:
        """Retrieve all indexed chunks for a specific document."""
        if self.collection is None:
            self._get_or_create_collection(reset=False)

        results = self.collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )

        chunks = []
        for i in range(len(results["ids"])):
            chunks.append({
                "chunk_id": results["ids"][i],
                "text": results["documents"][i],
                "metadata": results["metadatas"][i],
            })

        chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))
        return chunks
