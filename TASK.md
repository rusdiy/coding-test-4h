# Task Checklist — Multimodal Document Chat System

> **Status Legend**: ⬜ Not started · 🔄 In progress · ✅ Done · ❌ Blocked

---

## Phase 0: Setup & Configuration
- [ ] Update `config.py` — add Gemini settings (`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`)
- [ ] Update `.env.example` — replace OpenAI vars with Gemini vars
- [ ] Update `requirements.txt` — remove `openai`, `langchain`, `langchain-openai`; add `google-generativeai`
- [ ] Update `document.py` model — change `Vector(1536)` → `Vector(768)` for Gemini embeddings
- [ ] Update `config.py` — change `EMBEDDING_DIMENSION` default to `768`
- [ ] Verify Docker Compose still works with updated deps

## Phase 1: Document Processing Pipeline (`document_processor.py`)
- [ ] Implement `process_document()` — orchestrator method
  - Update status → parse with Docling → extract text/images/tables → generate embeddings → update status
- [ ] Implement `_chunk_text()` — structure-aware chunking
  - Use Docling's document structure (headings, paragraphs, sections)
  - Fallback to recursive splitting with overlap for long sections
  - Attach metadata: page number, section heading, chunk index, nearby image/table IDs
- [ ] Implement `_save_text_chunks()` — persist chunks with embeddings
- [ ] Implement `_save_image()` — save extracted image to disk + DB record
- [ ] Implement `_save_table()` — render table as image + store structured JSON + DB record
- [ ] Add error handling and status updates throughout

## Phase 2: Vector Store (`vector_store.py`)
- [ ] Initialize Gemini embedding model (`text-embedding-004`)
- [ ] Implement `generate_embedding()` — call Gemini Embeddings API
- [ ] Implement `store_chunk()` — generate embedding + create `DocumentChunk` record
- [ ] Implement `similarity_search()` — pgvector cosine similarity with optional document filter
- [ ] Implement `get_related_content()` — resolve image/table references from chunk metadata

## Phase 3: Chat Engine (`chat_engine.py`)
- [ ] Initialize Gemini LLM (`gemini-2.0-flash`)
- [ ] Implement `_load_conversation_history()` — load last N messages for multi-turn
- [ ] Implement `_search_context()` — delegate to VectorStore similarity search
- [ ] Implement `_find_related_media()` — extract image/table refs from context chunks
- [ ] Implement `_generate_response()` — build prompt with context + history + media refs → call Gemini
- [ ] Implement `process_message()` — full RAG orchestration
- [ ] Design system prompt with grounding instructions and source citation

## Phase 4: API Wiring
- [ ] `documents.py` — wire `DocumentProcessor` in upload endpoint via BackgroundTasks
- [ ] `chat.py` — uncomment and wire `ChatEngine.process_message()`
- [ ] Add proper error handling / try-except in both endpoints
- [ ] Test API endpoints manually via Swagger

## Phase 5: Frontend Enhancements
- [ ] Upload page — add processing status polling after upload
- [ ] Chat page — improve source rendering (collapsible, better image display)
- [ ] Document detail page — add "processing" spinner / auto-refresh while status is `processing`
- [ ] General UX polish

## Phase 6: Testing & Demo
- [ ] Download "Attention Is All You Need" PDF
- [ ] Upload and verify processing completes without errors
- [ ] Test: "Show me the Transformer architecture diagram" → should retrieve Figure 1
- [ ] Test: "What are the BLEU scores?" → should retrieve Table data
- [ ] Test: "Explain self-attention" → should retrieve relevant text sections
- [ ] Capture screenshots for submission

## Phase 7: Documentation (DESIGN.md)
- [ ] Finalize Design Choice Document (chunking + multimodal linking)
- [ ] Finalize Evaluation Pipeline Design
- [ ] Finalize Prompt Versioning Strategy
- [ ] Review and polish DESIGN.md for submission quality

---

## Decision Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| 1 | Use Gemini (free tier) instead of OpenAI | Cost-free; `gemini-2.0-flash` for chat, `text-embedding-004` for embeddings | 2026-03-22 |
| 2 | Single `DESIGN.md` instead of multiple docs | Covers all Part B deliverables in one cohesive document; easier for evaluators | 2026-03-22 |
| 3 | Keep Docling for PDF parsing | Explicitly required by the test; good multimodal extraction | 2026-03-22 |
| 4 | Embedding dim 768 (Gemini default) | `text-embedding-004` default output; no need to customize | 2026-03-22 |
