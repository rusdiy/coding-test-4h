# Design Document — Multimodal Document Chat System

> **Author**: Rusdiy Afkar  
> **Date**: 2026-03-22  
> **Role**: AI Context Architect & Engineering Lead  

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Design Choice Document](#2-design-choice-document)
   - 2.1 Chunking Strategy
   - 2.2 Multimodal Linking Strategy
3. [Evaluation Pipeline Design](#3-evaluation-pipeline-design)
4. [Prompt Versioning Strategy](#4-prompt-versioning-strategy)
5. [Technology Decisions & Trade-offs](#5-technology-decisions--trade-offs)

---

## 1. System Architecture Overview

### High-Level Flow

```
PDF Upload → Docling Parse → [Text Chunks + Images + Tables]
                                     ↓
                              Gemini Embeddings (gemini-embedding-2-preview)
                                     ↓
                              pgvector Storage
                                     ↓
User Query → Embed Query → Cosine Similarity Search → Top-K Chunks
                                     ↓
                         Resolve Related Images/Tables
                                     ↓
                    Build Multimodal Prompt (context + history + media)
                                     ↓
                         Gemini 2.5 Flash → Response
                                     ↓
                    Format Answer + Sources → Frontend
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| **DocumentProcessor** | `document_processor.py` | PDF parsing via Docling, text chunking, image/table extraction, metadata creation |
| **VectorStore** | `vector_store.py` | Embedding generation (Gemini), pgvector storage, cosine similarity search, related content resolution |
| **ChatEngine** | `chat_engine.py` | RAG orchestration, conversation history, prompt construction, LLM invocation (Gemini), response formatting |

### Data Model Relationships

```
Document (1) ──→ (N) DocumentChunk   [text + embedding + metadata]
    │               └── metadata.related_images: [image_id, ...]
    │               └── metadata.related_tables: [table_id, ...]
    │
    ├──→ (N) DocumentImage            [file on disk + caption + page]
    │
    └──→ (N) DocumentTable            [rendered image + JSON data + caption + page]

Conversation (1) ──→ (N) Message      [role + content + sources JSON]
    └── document_id (optional scope)
```

---

## 2. Design Choice Document

### 2.1 Chunking Strategy

#### Approach: **Structure-Aware Chunking with Docling**

Rather than naive fixed-size chunking, we leverage Docling's document structure awareness to produce semantically meaningful chunks.

**Strategy (in priority order):**

1. **Docling Structural Elements First**: Docling parses the PDF into a structured representation with headings, paragraphs, lists, and sections. Each structural element (paragraph, list item, section) becomes a candidate chunk.

2. **Section-Based Grouping**: Short consecutive elements under the same heading are merged into a single chunk to preserve context. For example, a heading + its 2-3 short paragraphs become one chunk.

3. **Overflow Splitting**: If a structural element exceeds `CHUNK_SIZE` (default: 1000 characters), it is split using recursive character splitting with `CHUNK_OVERLAP` (default: 200 characters) to maintain continuity across chunk boundaries.

4. **Metadata Enrichment**: Every chunk carries:
   - `page_number` — which page(s) the chunk spans
   - `section_heading` — the nearest parent heading (e.g., "3.2 Scaled Dot-Product Attention")
   - `chunk_index` — global ordering within the document
   - `related_images` — IDs of images on the same page or referenced in text
   - `related_tables` — IDs of tables on the same page or referenced in text

#### Why Not Fixed-Size Chunking?

Fixed-size (e.g., 500-token) chunking is the simplest approach, but it:
- Splits mid-sentence and mid-paragraph, destroying semantic coherence
- Loses structural context (which section or subsection does this belong to?)
- Makes retrieval noisier — a chunk about "Training" might contain half a sentence from "Results"

#### Why Not Pure Semantic Chunking (e.g., embedding-based splitting)?

Embedding-based semantic chunking (split where cosine similarity between consecutive sentences drops) is elegant but:
- Computationally expensive at ingestion time (requires embedding every sentence)
- Adds latency to the processing pipeline
- Docling already provides structural boundaries that are a strong proxy for semantic boundaries

#### Chunk Size Rationale

- **1000 characters (~200-250 tokens)**: Small enough for precise retrieval, large enough to carry a complete thought. Research papers have dense, technical paragraphs that benefit from slightly larger chunks.
- **200 character overlap**: Ensures cross-chunk continuity. If a key term appears at a chunk boundary, both adjacent chunks will contain it.

---

### 2.2 Multimodal Linking Strategy

#### Approach: **Page Proximity + Text Reference Detection**

The core challenge: when a user asks "What does the Transformer architecture look like?", the system needs to retrieve Figure 1 — but Figure 1 is an image, not text. How do we bridge text-based retrieval to image/table results?

**Linking Strategy (two-pronged):**

#### A. Page-Level Proximity (Primary)

When processing a document, images and tables are extracted with their page number. Text chunks on the same page are annotated with references to those images/tables:

```python
# During chunking, for each chunk on page N:
chunk.metadata = {
    "related_images": [id for img in images if img.page_number == page_number],
    "related_tables": [id for tbl in tables if tbl.page_number == page_number]
}
```

This means that when a text chunk about "multi-head attention" (found on page 3) is retrieved, it automatically carries references to Figure 1 (also on page 3).

#### B. Caption/Reference Text Injection (Secondary)

Image and table captions (e.g., "Figure 1: The Transformer model architecture") are:
1. Stored as `caption` in their DB record
2. **Also appended to nearby text chunks** as additional context, so that embedding search on "Transformer architecture diagram" has a higher chance of matching

This creates a "semantic halo" around each image/table — the caption text becomes part of the searchable embedding space.

#### Why Not Embed Images Directly?

Multimodal embedding models (e.g., CLIP) could embed images alongside text. However:
- Adds complexity and a separate embedding model
- While Gemini's `gemini-embedding-2-preview` does support multimodal content, caption-based linking provides explicit structural guarantees.
- Caption-based linking achieves ~80% of the benefit with minimal complexity
- Within the scope of this test, caption + proximity linking is the pragmatic choice

---

## 3. Evaluation Pipeline Design

> *"If I were to build an eval pipeline, I would check..."*

### Quality Metrics Framework

#### 3.1 Retrieval Quality

| Metric | What It Measures | How to Compute |
|--------|-----------------|----------------|
| **Context Precision** | Are the retrieved chunks relevant to the query? | For each query, have a human (or LLM-as-judge) rate each retrieved chunk as relevant/irrelevant. Precision = relevant_chunks / total_retrieved. |
| **Context Recall** | Does the retrieval capture all necessary information? | Given a gold-standard answer, check if the retrieved context contains sufficient information to produce that answer. |
| **Hit Rate @K** | Does the correct passage appear in the top K results? | Binary: Is the ground-truth chunk in the top-K retrieved results? |

#### 3.2 Answer Quality (RAGAS-inspired)

| Metric | What It Measures | How to Compute |
|--------|-----------------|----------------|
| **Faithfulness** | Is the answer grounded in the retrieved context? | Decompose the answer into atomic claims. For each claim, check if it can be inferred from the context. Score = supported_claims / total_claims. |
| **Answer Relevancy** | Does the answer address the question? | Generate N questions from the answer using an LLM. Compute the mean cosine similarity between the generated questions and the original question. |
| **Correctness** | Is the answer factually correct? | Compare against gold-standard answers using LLM-as-judge with a rubric. |

#### 3.3 Multimodal-Specific Metrics

| Metric | What It Measures | How to Compute |
|--------|-----------------|----------------|
| **Image Retrieval Recall** | When a question requires an image, does the system surface it? | Curate queries that require images (e.g., "Show the architecture diagram"). Check if the relevant image appears in sources. |
| **Table Data Accuracy** | When asked about table data, is the answer correct? | For table-specific queries (e.g., "What is the BLEU score for the base model?"), compare the extracted answer against the actual table cell value. |

#### 3.4 Practical Eval Pipeline Design

```
1. Curate Test Set
   - 20-30 question-answer pairs from the target PDF
   - Mix of: pure text, image-requiring, table-requiring, multi-hop
   - Include "unanswerable" questions (not in document)

2. Automated Scoring
   - Run all queries through the system
   - Use LLM-as-judge (Gemini) to score faithfulness + relevancy
   - Compute retrieval precision/recall against ground truth

3. Dashboard
   - Aggregate scores by query type (text/image/table)
   - Track degradation across prompt versions
   - Flag low-confidence answers for human review
```

---

## 4. Prompt Versioning Strategy

### Current Approach

For this implementation, prompts are defined as **Python constants in a dedicated module** (`prompts.py` or within `chat_engine.py`). This is a pragmatic choice for a single-developer project:

```python
# chat_engine.py
SYSTEM_PROMPT_V1 = """
You are a document analysis assistant. Answer questions based on the provided context.
...
"""
```

### Scaling Proposal: Prompt Registry

For a production system, I would propose the following architecture:

#### A. External Prompt Templates

Move prompts out of code into versioned YAML/JSON files:

```yaml
# prompts/system_prompt.yaml
version: "2.1"
created: "2026-03-22"
author: "rusdiy"
template: |
  You are a document analysis assistant. You have access to the following context
  extracted from a PDF document.

  ## Context
  {context}

  ## Instructions
  - Answer based ONLY on the provided context
  - Cite page numbers when possible
  - If an image or table is relevant, reference it by its caption
  - If you cannot answer from the context, say so explicitly
variables:
  - context
  - history
  - media_descriptions
```

#### B. Prompt Registry Service

```python
class PromptRegistry:
    """Central registry for prompt templates with versioning."""

    def get(self, name: str, version: str = "latest") -> PromptTemplate:
        """Retrieve a prompt template by name and version."""

    def register(self, name: str, template: PromptTemplate) -> str:
        """Register a new prompt version, returns version ID."""

    def compare(self, name: str, v1: str, v2: str) -> PromptDiff:
        """Diff two versions of a prompt."""

    def rollback(self, name: str, version: str) -> None:
        """Rollback to a previous version."""
```

#### C. A/B Testing Integration

```
Request → Load Prompt Version (based on experiment config)
       → Generate Response
       → Log: {query, prompt_version, response, latency, user_feedback}
       → Analyze: which version produces better faithfulness scores?
```

#### Why This Matters

- **Reproducibility**: Every response can be traced to a specific prompt version
- **Safe Iteration**: Change prompts without code deploys; rollback if quality drops
- **Collaboration**: Non-engineers (product, domain experts) can edit prompts via UI
- **Evaluation**: Compare prompt versions against the eval pipeline (Section 3)

---

## 5. Technology Decisions & Trade-offs

### LLM & Embeddings: Gemini (Free Tier)

| Choice | Value | Rationale |
|--------|-------|-----------|
| Chat Model | `gemini-2.5-flash` | Fast, capable, free tier generous (15 RPM / 1M TPM) |
| Embedding Model | `gemini-embedding-2-preview` | 768 dimensions (or 8192 limits), solid retrieval quality, free |
| Alternative Considered | OpenAI `gpt-4o-mini` + `text-embedding-3-small` | Better quality but requires paid API key |

### PDF Processing: Docling

- **Why Docling?**: Explicitly required by the test. Extracts structured document representation with text, images, tables, and spatial layout info.
- **Trade-off**: Docling is relatively new and APIs may be less stable than PyMuPDF/pdfplumber. But its structure-aware parsing is superior for our multimodal use case.

### Vector Store: pgvector

- **Why not Pinecone/Weaviate/Qdrant?**: pgvector runs in the same PostgreSQL instance (already provisioned). Zero additional infrastructure. For our scale (single PDF, ~100-200 chunks), pgvector performance is more than sufficient.
- **Trade-off**: Lacks advanced features (hybrid search, metadata filtering optimizations) that dedicated vector DBs offer. Acceptable for this scope.

### Embedding Dimension: 768

- Gemini `gemini-embedding-2-preview` default output dimension handling.
- Changed from the skeleton's `1536` (which was OpenAI-specific).
- 768 dimensions is a good balance between retrieval quality and storage/compute cost.
