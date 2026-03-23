# Multimodal Document Chat System

![Project Status](https://img.shields.io/badge/Status-Complete-success)
![Gemini](https://img.shields.io/badge/AI-Google_Gemini-blue)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)
![Next.js](https://img.shields.io/badge/Frontend-Next.js-black)

## Overview

This project is a fully functional **Multimodal Document Chat System**. It ingests PDF documents, parses them structurally (extracting text, images, and tables), embeds the content into a vector database, and allows users to converse with the document using an advanced RAG (Retrieval-Augmented Generation) pipeline.

This repository fulfills the requirements for the **AI Context Architect & Engineering Lead** coding test.

## Project Deliverables

- **Implementation**: The core pipeline (`document_processor.py`), vector store integration (`vector_store.py`), and RAG orchestrator (`chat_engine.py`) have been fully implemented using Google Gemini's models (`gemini-2.5-flash` and `gemini-embedding-2-preview`). Document parsing is facilitated intelligently by `Docling`.
- **Architectural & Design Choices**: Detailed in [`DESIGN.md`](./DESIGN.md). This covers strategies around structural chunking, spatial & semantic multimodal linking, dynamic evaluation pipelines, and scalable prompt versioning.
- **Task Verification**: See [`TASK.md`](./TASK.md) for the completion checklist of all requirements tracking the steps from environment setup through API integrations.
- **Original Instructions**: The original coding test requirements have been preserved in [`README_past.md`](./README_past.md).

## Quickstart & Installation

### Prerequisites
- Docker (20.10+) & Docker Compose
- Node.js 18.0+
- Python 3.11+
- [Google Gemini API Key](https://aistudio.google.com/app/apikey)

### Configuration
Clone the repository and define your environment variables. Check `.env.example` as a template for setting up the environment:
```bash
# Example setup for .env
GEMINI_API_KEY="your-gemini-key"
GEMINI_MODEL="gemini-2.5-flash"
GEMINI_EMBEDDING_MODEL="gemini-embedding-2-preview"
```

### Running the Application (Docker)
The easiest way to bootstrap the application is via Docker Compose at the root of the project:
```bash
docker-compose up -d --build
```
This spins up PostgreSQL with pgvector, Redis, the FastApi Backend, and the Next.js Frontend.

- **Frontend Application**: `http://localhost:3000`
- **Backend API & Swagger**: `http://localhost:8000/docs`

## Usage Guide
1. **Upload Documents**: Navigate to `http://localhost:3000/upload` and upload the test paper (e.g., `1706.03762.pdf` - Attention Is All You Need).
2. **Background Processing**: The backend leverages `Docling` to extract structured sections, isolate images, render tables, and compute Gemini 768-dimension embeddings, which are written parallel to `pgvector`.
3. **Conversational AI**: Navigate to the Chat interface to query against the processed material. The chat engine retrieves relevant text, maps adjacent images/tables based on document structure, and generates highly grounded answers.
   - *Example 1 (Images)*: "Show me the Transformer architecture diagram."
   - *Example 2 (Tables)*: "What are the BLEU scores listed for the base model?"
   - *Example 3 (Concept)*: "Explain self-attention."

## Built With
- **Algorithms & Core Logic**: Custom structural chunking logic + "semantic halo" linking
- **Backend Architecture**: FastAPI + SQLAlchemy + Data structures mapping
- **AI & RAG**: Google Generative AI (Gemini Flash & Embeddings), pgvector for similarity searching
- **Document Processing**: Docling
- **Frontend Stack**: Next.js + TailwindCSS + React Hooks

## Author
**Rusdiy Afkar**
