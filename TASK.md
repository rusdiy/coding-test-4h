# Task Checklist — Multimodal Document Chat System

> **Status Legend**: ⬜ Not started · 🔄 In progress · ✅ Done · ❌ Blocked

---

## Phase 0: Setup & Configuration ✅
- [x] Update `config.py` — add Gemini settings (`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`)
- [x] Update `.env.example` — replace OpenAI vars with Gemini vars
- [x] Update `requirements.txt` — remove `openai`, `langchain`, `langchain-openai`; add `google-generativeai`
- [x] Update `document.py` model — change `Vector(1536)` → `Vector(768)` for Gemini embeddings
- [x] Update `config.py` — change `EMBEDDING_DIMENSION` default to `768`
- [x] Update `docker-compose.yml` — Gemini env vars
- [x] Update service skeletons — Gemini references in TODO comments

## Phase 1: Document Processing Pipeline (`document_processor.py`) ✅
- [x] Implement `process_document()` — orchestrator method
  - Update status → parse with Docling → extract text/images/tables → generate embeddings → update status
- [x] Implement `_extract_and_chunk_text()` + `_create_chunks()` — structure-aware chunking
  - Uses Docling's document structure (headings, paragraphs, sections)
  - Fallback to paragraph-boundary splitting with overlap for long sections
  - Attaches metadata: page number, section heading, chunk index, nearby image/table IDs
- [x] Implement `_save_text_chunks()` — persist chunks with embeddings via VectorStore
- [x] Implement `_extract_and_save_images()` — save extracted images to disk + DB record
- [x] Implement `_extract_and_save_tables()` — render table as image + store structured JSON + DB record
- [x] Add error handling and status updates throughout
- [x] Implement caption injection ("semantic halo") for multimodal linking

## Phase 2: Vector Store (`vector_store.py`) ✅
- [x] Initialize Gemini embedding model (`gemini-embedding-2-preview`) — lazy config on first call
- [x] Implement `generate_embedding()` — call Gemini Embeddings API with task_type support
- [x] Implement `store_chunk()` — generate embedding + create `DocumentChunk` record
- [x] Implement `similarity_search()` — pgvector cosine similarity with optional document filter + inline media resolution
- [x] Implement `get_related_content()` — resolve image/table references from chunk metadata

## Phase 3: Chat Engine (`chat_engine.py`) ✅
- [x] Initialize Gemini LLM (`gemini-2.5-flash`) — lazy init via `_get_model()`
- [x] Implement `_load_conversation_history()` — load last N messages for multi-turn
- [x] Implement `_search_context()` — delegate to VectorStore similarity search
- [x] Implement `_find_related_media()` — deduplicate image/table refs from context chunks
- [x] Implement `_generate_response()` — build prompt with context + history + media refs → call Gemini
- [x] Implement `process_message()` — full RAG orchestration
- [x] Design system prompt (v1) with grounding instructions and source citation
- [x] Prompt templates stored as versioned constants (SYSTEM_PROMPT_V1, CONTEXT_TEMPLATE, USER_TEMPLATE)

## Phase 4: API Wiring ✅
- [x] `documents.py` — wire `DocumentProcessor` in upload endpoint via BackgroundTasks
  - Created `_process_document_background()` helper with fresh DB session + asyncio.run()
- [x] `chat.py` — wire `ChatEngine.process_message()` with error handling
  - Falls back to friendly error message if ChatEngine fails
- [x] Add proper error handling / try-except in both endpoints
- [x] Added logging to both API modules

## Phase 5: Frontend Enhancements ✅
- [x] Upload page — drag-and-drop + processing status polling (5s interval) + auto-redirect on completion
- [x] Chat page — collapsible source panel, color-coded types (text/image/table), match % display, loading dots
- [x] Document detail page — auto-refresh while processing, styled stats grid, status badges, spinner
- [x] General UX polish — error states, empty states, helpful prompts

## Phase 6: Testing & Demo
- [x] Download "Attention Is All You Need" PDF
- [x] Upload and verify processing completes without errors
- [x] Test: "Show me the Transformer architecture diagram" → should retrieve Figure 1
- [x] Test: "What are the BLEU scores?" → should retrieve Table data
- [x] Test: "Explain self-attention" → should retrieve relevant text sections
- [x] Capture screenshots for submission

## Phase 7: Documentation (DESIGN.md)
- [x] Finalize Design Choice Document (chunking + multimodal linking)
- [x] Finalize Evaluation Pipeline Design
- [x] Finalize Prompt Versioning Strategy
- [x] Review and polish DESIGN.md for submission quality

---

## Decision Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| 1 | Use Gemini (free tier) instead of OpenAI | Cost-free; `gemini-2.5-flash` for chat, `gemini-embedding-2-preview` for embeddings | 2026-03-22 |
| 2 | Single `DESIGN.md` instead of multiple docs | Covers all Part B deliverables in one cohesive document; easier for evaluators | 2026-03-22 |
| 3 | Keep Docling for PDF parsing | Explicitly required by the test; good multimodal extraction | 2026-03-22 |
| 4 | Embedding dim 768 (Gemini default) | `gemini-embedding-2-preview` default output; no need to customize | 2026-03-22 |
