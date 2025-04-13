# Vector Store

This directory contains implementations for different vector stores used in the application.

## Vector Store Types

The application supports three vector store implementations:

1. **Standard Store** (`pdf_pages_store.py`)
   - Processes PDF content page-by-page
   - Preserves full page context
   - Uses `all-MiniLM-L6-v2` Sentence Transformer model (384 dimensions)
   - Direct Qdrant integration with simple page-level search

2. **Semantic Store** (`semantic_store.py`) 
   - Chunks content into semantically meaningful paragraphs
   - Uses `text-embedding-3-small` OpenAI model (1536 dimensions)
   - Implements hybrid search combining vector similarity with BM25 keyword search
   - Provides advanced reranking of search results

3. **Haystack Store** (`haystack_store.py`)
   - Uses Haystack framework with Qdrant backend
   - Leverages Sentence Transformers for local embedding generation
   - Maintains compatibility with Haystack 2.x API for document filtering
   - Offers specialized search methods like `search_monster_info()`

## Search Helper Abstraction

The `SearchHelper` base class provides a standardized interface for all vector store implementations, reducing code duplication and ensuring consistent error handling. Each store implements:

- Basic vector search (similarity)
- Filter-based search (metadata filtering)
- Document retrieval by source/page
- All-document retrieval

The abstraction consists of:

- **Public methods**: Common interface for all stores with standardized error handling
- **Protected abstract methods**: Implemented by each specific store
- **Helper methods**: Common utilities for all stores

## Factory Pattern

The `__init__.py` file implements a factory pattern to create and cache vector store instances based on the requested type. This allows the application to easily switch between different vector store implementations at runtime. 