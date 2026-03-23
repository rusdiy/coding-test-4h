"""
Vector store service using pgvector + Gemini embeddings.

Handles:
- Embedding generation via Google Gemini text-embedding-004
- Chunk storage with vector embeddings in PostgreSQL/pgvector
- Cosine similarity search with optional document filtering
- Related content (images/tables) resolution from chunk metadata
"""
import logging
from typing import List, Dict, Any, Optional

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.document import DocumentChunk, DocumentImage, DocumentTable
from app.core.config import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Vector store for document embeddings and similarity search.

    Uses:
    - Google Gemini gemini-embedding-2-preview for embedding generation (768 dims)
    - PostgreSQL pgvector for storage and cosine similarity search
    """

    def __init__(self, db: Session):
        self.db = db
        self._client = None
        self._ensure_extension()

    def _ensure_extension(self):
        """Ensure pgvector extension is enabled in PostgreSQL."""
        try:
            self.db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            self.db.commit()
        except Exception as e:
            logger.debug(f"pgvector extension check: {e}")
            self.db.rollback()

    def _get_client(self):
        """Lazily create the Google GenAI client (only once)."""
        if self._client is not None:
            return self._client

        from google import genai

        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please add it to your .env file."
            )

        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info(
            f"Gemini client configured for embeddings: {settings.GEMINI_EMBEDDING_MODEL}"
        )
        return self._client

    # =========================================================================
    # Embedding Generation
    # =========================================================================

    async def generate_embedding(
        self, content: str, task_type: str = "retrieval_document"
    ) -> np.ndarray:
        """
        Generate embedding vector for text using Gemini.

        Args:
            content: Text to embed
            task_type: Either "retrieval_document" (for storing) or
                       "retrieval_query" (for searching)

        Returns:
            numpy array of shape (768,)
        """
        client = self._get_client()

        # Truncate very long text to avoid API limits
        max_chars = 8000
        if len(content) > max_chars:
            content = content[:max_chars]

        import asyncio
        
        max_retries = 3
        base_delay = 15
        
        for attempt in range(max_retries):
            try:
                result = await client.aio.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=content,
                    config={
                        "task_type": task_type,
                        "output_dimensionality": settings.EMBEDDING_DIMENSION,
                    },
                )
                return np.array(result.embeddings[0].values, dtype=np.float32)
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limited by Gemini on embeddings (429). Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                    
                logger.error(f"Embedding generation failed: {e}")
                raise

    # =========================================================================
    # Chunk Storage
    # =========================================================================

    async def store_chunk(
        self,
        content: str,
        document_id: int,
        page_number: int,
        chunk_index: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentChunk:
        """
        Store a text chunk with its Gemini embedding.

        Args:
            content: Text content of the chunk
            document_id: Parent document ID
            page_number: Source page number
            chunk_index: Ordering index within the document
            metadata: Cross-reference metadata (related_images, related_tables, etc.)

        Returns:
            The created DocumentChunk record
        """
        # Generate embedding
        embedding = await self.generate_embedding(content, task_type="retrieval_document")

        # Create and persist the chunk
        chunk = DocumentChunk(
            document_id=document_id,
            content=content,
            embedding=embedding.tolist(),
            page_number=page_number,
            chunk_index=chunk_index,
            metadata=metadata or {},
        )
        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)

        logger.debug(
            f"Stored chunk {chunk_index} for document {document_id} "
            f"(page {page_number}, {len(content)} chars)"
        )
        return chunk

    # =========================================================================
    # Similarity Search
    # =========================================================================

    async def similarity_search(
        self,
        query: str,
        document_id: Optional[int] = None,
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using pgvector cosine similarity.

        Args:
            query: Search query text
            document_id: Optional document ID to scope the search
            k: Number of top results to return

        Returns:
            List of dicts with content, score, page_number, metadata,
            and resolved related_images / related_tables.
        """
        # Generate query embedding (note: task_type is retrieval_query)
        query_embedding = await self.generate_embedding(
            query, task_type="retrieval_query"
        )
        embedding_str = "[" + ",".join(str(x) for x in query_embedding.tolist()) + "]"

        # Build SQL query with pgvector cosine distance operator (<=>)
        sql = """
            SELECT
                id,
                content,
                page_number,
                chunk_index,
                metadata,
                1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
            FROM document_chunks
        """
        params: Dict[str, Any] = {"query_embedding": embedding_str, "k": k}

        if document_id is not None:
            sql += " WHERE document_id = :document_id"
            params["document_id"] = document_id

        sql += " ORDER BY embedding <=> CAST(:query_embedding AS vector) LIMIT :k"

        try:
            result = self.db.execute(text(sql), params)
            rows = result.fetchall()
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            self.db.rollback()
            
            # Diagnostic: check if chunks exist at all
            try:
                diag_sql = "SELECT COUNT(*) as cnt FROM document_chunks"
                diag_params: Dict[str, Any] = {}
                if document_id is not None:
                    diag_sql += " WHERE document_id = :document_id"
                    diag_params["document_id"] = document_id
                diag_result = self.db.execute(text(diag_sql), diag_params)
                count = diag_result.scalar()
                logger.error(f"Diagnostic: document_chunks count = {count} (doc_id={document_id})")
            except Exception as diag_e:
                logger.error(f"Diagnostic query also failed: {diag_e}")
                self.db.rollback()
            
            return []

        logger.info(
            f"Similarity search raw results: {len(rows)} rows returned"
        )

        # Build results with resolved related content
        results = []
        for row in rows:
            chunk_metadata = row.metadata if row.metadata else {}

            entry = {
                "chunk_id": row.id,
                "content": row.content,
                "page_number": row.page_number,
                "chunk_index": row.chunk_index,
                "score": float(row.similarity) if row.similarity else 0.0,
                "metadata": chunk_metadata,
                "related_images": [],
                "related_tables": [],
            }

            # Resolve related images from metadata
            image_ids = chunk_metadata.get("related_images", [])
            if image_ids:
                images = (
                    self.db.query(DocumentImage)
                    .filter(DocumentImage.id.in_(image_ids))
                    .all()
                )
                entry["related_images"] = [
                    {
                        "id": img.id,
                        "url": f"/uploads/images/{os.path.basename(img.file_path)}",
                        "caption": img.caption,
                        "page": img.page_number,
                    }
                    for img in images
                ]

            # Resolve related tables from metadata
            table_ids = chunk_metadata.get("related_tables", [])
            if table_ids:
                tables = (
                    self.db.query(DocumentTable)
                    .filter(DocumentTable.id.in_(table_ids))
                    .all()
                )
                entry["related_tables"] = [
                    {
                        "id": tbl.id,
                        "url": f"/uploads/tables/{os.path.basename(tbl.image_path)}",
                        "caption": tbl.caption,
                        "page": tbl.page_number,
                        "data": tbl.data,
                    }
                    for tbl in tables
                ]

            results.append(entry)

        logger.info(
            f"Similarity search: query='{query[:50]}...', "
            f"doc_id={document_id}, results={len(results)}"
        )
        return results

    # =========================================================================
    # Related Content Resolution
    # =========================================================================

    async def get_related_content(
        self, chunk_ids: List[int]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get related images and tables for a set of chunk IDs.

        Resolves the related_images and related_tables IDs stored in each
        chunk's metadata into full records.

        Returns:
            {"images": [...], "tables": [...]}
        """
        image_ids_set: set = set()
        table_ids_set: set = set()

        # Collect all referenced media IDs from chunk metadata
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.id.in_(chunk_ids))
            .all()
        )
        for chunk in chunks:
            meta = chunk.metadata or {}
            image_ids_set.update(meta.get("related_images", []))
            table_ids_set.update(meta.get("related_tables", []))

        # Resolve images
        images = []
        if image_ids_set:
            db_images = (
                self.db.query(DocumentImage)
                .filter(DocumentImage.id.in_(list(image_ids_set)))
                .all()
            )
            images = [
                {
                    "id": img.id,
                    "url": f"/uploads/images/{os.path.basename(img.file_path)}",
                    "caption": img.caption,
                    "page": img.page_number,
                    "width": img.width,
                    "height": img.height,
                }
                for img in db_images
            ]

        # Resolve tables
        tables = []
        if table_ids_set:
            db_tables = (
                self.db.query(DocumentTable)
                .filter(DocumentTable.id.in_(list(table_ids_set)))
                .all()
            )
            tables = [
                {
                    "id": tbl.id,
                    "url": f"/uploads/tables/{os.path.basename(tbl.image_path)}",
                    "caption": tbl.caption,
                    "page": tbl.page_number,
                    "data": tbl.data,
                    "rows": tbl.rows,
                    "columns": tbl.columns,
                }
                for tbl in db_tables
            ]

        return {"images": images, "tables": tables}


# Required for os.path.basename in URL construction
import os
