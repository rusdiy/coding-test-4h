"""
Chat engine service for multimodal RAG.

Orchestrates the full retrieval-augmented generation flow:
1. Load conversation history (multi-turn support)
2. Search vector store for relevant context
3. Resolve related images and tables
4. Build grounded prompt with context + history + media
5. Generate response via Gemini LLM
6. Format response with cited sources
"""
import os
import time
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message
from app.models.document import DocumentImage, DocumentTable
from app.services.vector_store import VectorStore
from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Prompt Templates (v1)
#
# Design note: Currently stored as constants here for simplicity.
# For scaling, see DESIGN.md §4 "Prompt Versioning Strategy" —
# these would move to external YAML templates with a PromptRegistry.
# =============================================================================

SYSTEM_PROMPT_V1 = """You are an expert document analysis assistant. Your role is to answer questions accurately based on the provided context extracted from a PDF document.

## Rules
1. Answer ONLY based on the provided context. Do NOT use outside knowledge.
2. If the context does not contain enough information to answer, say: "I don't have enough information in the document to answer that question."
3. When citing information, mention the page number (e.g., "According to page 3...").
4. If relevant images or tables are available, reference them by their caption/description.
5. Use clear formatting: bullet points, numbered lists, and bold text for key terms.
6. Be concise but thorough. Prefer direct answers over lengthy explanations.
7. For technical questions, use precise terminology from the document."""

CONTEXT_TEMPLATE = """## Retrieved Context

{context_blocks}

## Available Media
{media_block}"""

USER_TEMPLATE = """Based on the document context provided above, please answer the following question:

{question}"""


class ChatEngine:
    """
    Multimodal chat engine with RAG (Retrieval-Augmented Generation).

    Flow:
        User Message → Vector Search → Context + Media Resolution
        → Prompt Construction (system + history + context + question)
        → Gemini LLM → Formatted Response with Sources
    """

    def __init__(self, db: Session):
        self.db = db
        self.vector_store = VectorStore(db)
        self._client = None

    def _get_client(self):
        """Lazily initialize the Google GenAI client."""
        if self._client is None:
            from google import genai

            if not settings.GEMINI_API_KEY:
                raise ValueError(
                    "GEMINI_API_KEY is not set. Please add it to your .env file."
                )
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
            logger.info(f"Gemini client initialized: {settings.GEMINI_MODEL}")
        return self._client

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    async def process_message(
        self,
        conversation_id: int,
        message: str,
        document_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Process a chat message end-to-end.

        Steps:
        1. Load conversation history for multi-turn context
        2. Search vector store for relevant chunks
        3. Resolve related images and tables
        4. Build prompt with context + history + media descriptions
        5. Call Gemini LLM
        6. Format response with sources

        Returns:
            {
                "answer": "...",
                "sources": [...],
                "processing_time": 2.5
            }
        """
        start_time = time.time()

        try:
            # Step 1: Load conversation history
            history = await self._load_conversation_history(conversation_id)

            # Step 2: Search for relevant context
            context_chunks = await self._search_context(
                query=message,
                document_id=document_id,
                k=settings.TOP_K_RESULTS,
            )

            # Step 3: Resolve related media from context
            media = await self._find_related_media(context_chunks)

            # Step 4: Generate LLM response
            answer = await self._generate_response(
                message=message,
                context=context_chunks,
                history=history,
                media=media,
            )

            # Step 5: Format sources for frontend
            sources = self._format_sources(context_chunks, media)

            processing_time = round(time.time() - start_time, 2)

            return {
                "answer": answer,
                "sources": sources,
                "processing_time": processing_time,
            }

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "answer": f"I encountered an error while processing your question: {str(e)}",
                "sources": [],
                "processing_time": round(time.time() - start_time, 2),
            }

    # =========================================================================
    # Conversation History
    # =========================================================================

    async def _load_conversation_history(
        self, conversation_id: int, limit: int = 5
    ) -> List[Dict[str, str]]:
        """
        Load recent conversation messages for multi-turn context.

        Returns the last `limit` message pairs formatted for LLM context.
        """
        messages = (
            self.db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit * 2)  # Get pairs of user+assistant
            .all()
        )

        # Reverse to chronological order
        messages.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    # =========================================================================
    # Context Search
    # =========================================================================

    async def _search_context(
        self,
        query: str,
        document_id: Optional[int] = None,
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search vector store for relevant document chunks."""
        return await self.vector_store.similarity_search(
            query=query,
            document_id=document_id,
            k=k,
        )

    # =========================================================================
    # Related Media Resolution
    # =========================================================================

    async def _find_related_media(
        self, context_chunks: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Collect unique related images and tables from retrieved context chunks.

        Strategy:
        1. First, use explicitly linked media from chunk metadata (related_images, related_tables)
        2. Fallback: query DB for images/tables on the same pages as retrieved chunks
           (handles cases where Docling cross-references weren't resolved during processing)
        """
        seen_image_ids: set = set()
        seen_table_ids: set = set()
        seen_media_keys: set = set()  # Used for semantic deduplication (page + caption)
        images: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []

        # Strategy 1: Explicitly linked media from chunk metadata
        for chunk in context_chunks:
            for img in chunk.get("related_images", []):
                media_key = f"img_{img.get('page')}_{img.get('caption')}"
                if img["id"] not in seen_image_ids and media_key not in seen_media_keys:
                    seen_image_ids.add(img["id"])
                    seen_media_keys.add(media_key)
                    images.append(img)

            for tbl in chunk.get("related_tables", []):
                media_key = f"tbl_{tbl.get('page')}_{tbl.get('caption')}"
                if tbl["id"] not in seen_table_ids and media_key not in seen_media_keys:
                    seen_table_ids.add(tbl["id"])
                    seen_media_keys.add(media_key)
                    tables.append(tbl)

        # Strategy 2: Page-based fallback — query DB for media on the same pages
        if not images or not tables:
            page_numbers = set()
            document_id = None
            
            # Only use the top 2 most relevant chunks to avoid pulling in too many irrelevant images
            for chunk in context_chunks[:2]:
                if chunk.get("page_number"):
                    page_numbers.add(chunk["page_number"])
                if chunk.get("metadata", {}).get("document_id"):
                    document_id = chunk["metadata"]["document_id"]

            page_numbers.discard(0)  # Remove page 0 if present

            if page_numbers:
                # Fallback: find images on relevant pages
                if not images:
                    try:
                        query = self.db.query(DocumentImage).filter(
                            DocumentImage.page_number.in_(page_numbers)
                        )
                        if document_id:
                            query = query.filter(DocumentImage.document_id == document_id)
                        db_images = query.all()
                        for img in db_images:
                            media_key = f"img_{img.page_number}_{img.caption}"
                            if img.id not in seen_image_ids and media_key not in seen_media_keys:
                                seen_image_ids.add(img.id)
                                seen_media_keys.add(media_key)
                                images.append({
                                    "id": img.id,
                                    "url": f"/uploads/images/{os.path.basename(img.file_path)}",
                                    "caption": img.caption,
                                    "page": img.page_number,
                                })
                        if db_images:
                            logger.info(f"Page-based fallback found {len(db_images)} images on pages {page_numbers}")
                    except Exception as e:
                        logger.error(f"Failed to query images by page: {e}")

                # Fallback: find tables on relevant pages
                if not tables:
                    try:
                        query = self.db.query(DocumentTable).filter(
                            DocumentTable.page_number.in_(page_numbers)
                        )
                        if document_id:
                            query = query.filter(DocumentTable.document_id == document_id)
                        db_tables = query.all()
                        for tbl in db_tables:
                            media_key = f"tbl_{tbl.page_number}_{tbl.caption}"
                            if tbl.id not in seen_table_ids and media_key not in seen_media_keys:
                                seen_table_ids.add(tbl.id)
                                seen_media_keys.add(media_key)
                                tables.append({
                                    "id": tbl.id,
                                    "url": f"/uploads/tables/{os.path.basename(tbl.image_path)}",
                                    "caption": tbl.caption,
                                    "page": tbl.page_number,
                                    "data": tbl.data,
                                })
                        if db_tables:
                            logger.info(f"Page-based fallback found {len(db_tables)} tables on pages {page_numbers}")
                    except Exception as e:
                        logger.error(f"Failed to query tables by page: {e}")

        logger.info(f"Related media resolved: {len(images)} images, {len(tables)} tables")
        return {"images": images, "tables": tables}

    # =========================================================================
    # LLM Response Generation
    # =========================================================================

    async def _generate_response(
        self,
        message: str,
        context: List[Dict[str, Any]],
        history: List[Dict[str, str]],
        media: Dict[str, List[Dict[str, Any]]],
    ) -> str:
        """
        Build a grounded prompt and generate a response via Gemini.

        Prompt structure:
        1. System prompt (passed via system_instruction config)
        2. Context block (retrieved chunks with page numbers)
        3. Media block (descriptions of available images/tables)
        4. Conversation history
        5. Current user question
        """
        from google.genai import types

        client = self._get_client()

        # Build context block
        context_blocks = []
        for i, chunk in enumerate(context):
            page = chunk.get("page_number", "?")
            score = chunk.get("score", 0)
            section = chunk.get("metadata", {}).get("section_heading", "")
            header = f"[Source {i+1} | Page {page} | Relevance: {score:.2f}]"
            if section:
                header += f" Section: {section}"
            context_blocks.append(f"{header}\n{chunk['content']}")

        context_text = "\n\n---\n\n".join(context_blocks) if context_blocks else "No relevant context found in the document."

        # Build media block
        media_lines = []
        for img in media.get("images", []):
            caption = img.get("caption", "Untitled image")
            page = img.get("page", "?")
            media_lines.append(f"- 📷 Image (Page {page}): {caption}")
        for tbl in media.get("tables", []):
            caption = tbl.get("caption", "Untitled table")
            page = tbl.get("page", "?")
            media_lines.append(f"- 📊 Table (Page {page}): {caption}")

        media_block = "\n".join(media_lines) if media_lines else "No images or tables available for this context."

        # Assemble the full context prompt
        context_prompt = CONTEXT_TEMPLATE.format(
            context_blocks=context_text,
            media_block=media_block,
        )

        # Build chat contents for Gemini
        chat_contents = []

        # Add context as the first user message
        chat_contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=context_prompt)])
        )
        chat_contents.append(
            types.Content(role="model", parts=[types.Part.from_text(text="I've reviewed the document context and available media. I'm ready to answer your questions based on this information.")])
        )

        # Add conversation history
        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            chat_contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
            )

        # Add current question
        user_prompt = USER_TEMPLATE.format(question=message)
        chat_contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])
        )

        import asyncio
        
        # Call Gemini with retry logic for rate limits
        max_retries = 3
        base_delay = 15
        
        for attempt in range(max_retries):
            try:
                response = await client.aio.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=chat_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT_V1,
                    ),
                )
                answer = response.text
                logger.info(f"LLM response generated ({len(answer)} chars)")
                return answer
            
            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limited by Gemini (429). Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                    
                logger.error(f"Gemini generation failed: {e}", exc_info=True)
                raise RuntimeError(f"Failed to generate response: {e}")

    # =========================================================================
    # Source Formatting
    # =========================================================================

    def _format_sources(
        self,
        context: List[Dict[str, Any]],
        media: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Format sources for the frontend response.

        Combines text chunks, images, and tables into a unified source list
        that the frontend can render.
        """
        sources: List[Dict[str, Any]] = []

        # Add top text sources
        for chunk in context[:3]:
            sources.append({
                "type": "text",
                "content": chunk["content"],
                "page": chunk.get("page_number"),
                "score": chunk.get("score", 0.0),
            })

        # Add image sources
        for image in media.get("images", []):
            sources.append({
                "type": "image",
                "url": image["url"],
                "caption": image.get("caption"),
                "page": image.get("page"),
            })

        # Add table sources
        for table in media.get("tables", []):
            sources.append({
                "type": "table",
                "url": table["url"],
                "caption": table.get("caption"),
                "page": table.get("page"),
                "data": table.get("data"),
            })

        return sources
