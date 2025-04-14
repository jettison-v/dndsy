# DnDSy - D&D 2024 Rules Assistant

DnDSy is a web application that acts as an intelligent assistant for the 2024 Dungeons & Dragons ruleset (unofficially 5.5e). It uses Retrieval-Augmented Generation (RAG) to answer user questions based on official PDF source materials.

## Features

*   **Multiple RAG Approaches:** Choose between different vector store approaches for optimal retrieval:
    * **Standard:** Process PDFs page-by-page, embedding each page for broader context.
    * **Semantic:** Chunk content into semantically meaningful paragraphs, embedding each chunk for more precise search.
    * **Haystack (Qdrant):** Leverages the Haystack framework with Qdrant backend for advanced document retrieval.
    * **Haystack (Memory):** Uses in-memory storage with file persistence for deployments without Qdrant.
*   **Document Structure Detection:** Intelligently analyzes PDF formatting to identify:
    * Document hierarchy (chapters, sections, subsections)
    * Different heading levels based on font sizes and styles
    * Contextual relationship between content sections
*   **Context-Aware Search Results:** Shows proper document structure context in search results:
    * Displays hierarchical paths like "Chapter 5 > Equipment > Weapons"
    * Improves user understanding of where information comes from
    * Maintains the relationship between content and its place in the document
*   **RAG Chatbot:** Answers questions about D&D 2024 rules using provided PDFs as context.
*   **Streaming Responses:** Assistant responses are streamed word-by-word for a real-time feel.
*   **Markdown Formatting:** Assistant responses are formatted using Markdown for enhanced readability (headings, bold, lists, etc.).
*   **Source Attribution:** Shows which document and page number the answer was derived from.
*   **Source Navigation:** Displays source page content as images directly in the interface. Allows navigating between pages of the source document within the side panel.
*   **Modular Data Processing Pipeline:** Handles PDF parsing, text extraction, image generation, structure analysis, embedding generation, and vector store indexing.
*   **AWS S3 Integration:** Handles PDF source files and generated page images stored in AWS S3.
*   **Abstracted LLM Provider:** Easily switch between LLM providers (e.g., OpenAI, Anthropic) via environment variables.
*   **Cloud Ready:** Designed for deployment with Qdrant Cloud for vector storage and AWS S3 for file storage.
*   **Password Protected:** Simple login system to protect access.
*   **Dockerized:** Includes Docker setup for consistent development and deployment.

## Technology Stack

*   **Backend:** Python, Flask
*   **Vector Database:** Qdrant (Cloud recommended for deployment)
    *   Collections: `dnd_pdf_pages` (standard), `dnd_semantic` (semantic), `dnd_haystack` (haystack-qdrant)
    *   Optional in-memory persistence with pickle files for deployments without Qdrant
*   **LLM:** Pluggable via `llm_providers` (e.g., OpenAI, Anthropic)
*   **Embeddings:** Centralized in `embeddings` package.
    *   Standard: Sentence Transformers (`all-MiniLM-L6-v2`)
    *   Semantic: OpenAI (`text-embedding-3-small`) via API
    *   Haystack: Sentence Transformers (`all-MiniLM-L6-v2`)
*   **Vector Search:** Four distinct approaches
    *   Standard: Page-level context with `PdfPagesStore`
    *   Semantic: Fine-grained chunking with hybrid search in `SemanticStore`
    *   Haystack (Qdrant): Direct integration with Haystack framework in `HaystackQdrantStore`
    *   Haystack (Memory): In-memory storage with file persistence in `HaystackMemoryStore`
*   **PDF Parsing:** PyMuPDF (`fitz`)
*   **Data Ingestion & Processing:** Custom pipeline in `data_ingestion` package using `langchain` for chunking, custom structure analysis.
*   **Frontend:** HTML, CSS, JavaScript (with Marked.js for Markdown rendering)
*   **Cloud Storage:** AWS S3 (Bucket name example: `askdnd-ai`)
*   **Deployment:** Docker, Gunicorn, Heroku (or similar platform)

## Project Structure

```
dndsy/
├── .env.example             # Example environment variables
├── .gitignore
├── Dockerfile               # For building the application container
├── README.md                # This file
├── app.py                   # Main Flask application entry point
├── data/                    # Data storage
│   ├── haystack_store/      # Storage for Haystack Memory persistence files
├── data_ingestion/          # Core data processing and ingestion logic
│   ├── __init__.py
│   ├── processor.py         # Handles PDF download, parsing, image gen, embedding calls
│   └── structure_analyzer.py# Utility for analyzing PDF structure and hierarchy
├── embeddings/              # Handles embedding model loading and vector generation
│   ├── __init__.py
│   └── model_provider.py    # Provides functions to get embeddings for text
├── extractors/              # Data extractors for content sources
│   └── __init__.py
├── flask_session/           # Storage for Flask session files
├── llm.py                   # Handles RAG orchestration (query embedding, search, context, LLM call)
├── llm_providers/           # Abstraction layer for different LLM APIs
│   ├── __init__.py
│   ├── base.py
│   └── openai.py            # (Example: Add anthropic.py etc. here)
├── logs/                    # Centralized directory for log files
├── requirements.txt         # Python dependencies
├── scripts/                 # Executable management/utility scripts
│   ├── __init__.py
│   ├── README.md            # Documentation for available scripts
│   ├── manage_vector_stores.py # Script to reset DB and trigger data processing
│   ├── load_haystack_store.py # Script to load documents into Haystack
│   └── setup_env.py         # Helper to create initial .env file
├── static/
│   ├── css/style.css
│   ├── img/
│   └── js/
│       ├── chat.js
│       ├── marked.min.js
│       └── source_viewer.js
├── templates/
│   ├── index.html
│   └── login.html
├── tests/                   # Test scripts and fixtures
│   ├── __init__.py
│   ├── README.md            # Test documentation
│   ├── test_api.py
│   ├── test_vector_store.py
│   └── vector_store/        # Vector store specific tests
│       ├── README.md
│       └── check_qdrant.py
├── utils/                   # General utility functions (if any)
│   └── __init__.py
├── vector_store/
│   ├── __init__.py          # Vector store factory
│   ├── haystack/            # Haystack implementations
│   │   ├── __init__.py
│   │   ├── common.py        # Shared utilities for Haystack implementations
│   │   ├── memory_store.py  # In-memory implementation with file persistence
│   │   └── qdrant_store.py  # Qdrant backend implementation
│   ├── pdf_pages_store.py   # Standard Qdrant interaction (page-level)
│   ├── search_helper.py     # Base class for vector stores
│   └── semantic_store.py    # Semantic Qdrant interaction (chunk-level, hybrid search)
└── docker/
    ├── docker-compose.yml   # Docker Compose for local development (app + Qdrant)
    └── Dockerfile           # For building the application container
```

## Local Development Setup

1.  **Prerequisites:**
    *   Python 3.11+ (3.11.7 specifically used in production as defined in `runtime.txt` and `.python-version`). It is recommended to use a Python version manager like `pyenv` to install and manage Python versions.
    *   Docker & Docker Compose (for running Qdrant locally easily)
    *   AWS Account & S3 Bucket (for PDF/image storage)
    *   LLM API Key (e.g., OpenAI, Anthropic)
    *   Qdrant Cloud Account (Optional, but recommended for deployment/easier setup)

2.  **Clone Repository:**
    ```bash
    git clone <your-repo-url>
    cd dndsy
    ```

3.  **Python Environment:**
    *   Ensure you are using Python 3.11.7. If using `pyenv`, it should automatically switch to this version when you `cd` into the directory (due to the `.python-version` file). You can verify with `python --version`.
    *   Create and activate a virtual environment. This isolates project dependencies:
        ```bash
        # Make sure you are using Python 3.11.7 before running this
        python -m venv venv
        # Activate the environment (syntax varies by shell)
        source venv/bin/activate  # On Bash/Zsh
        # venv\Scripts\activate   # On Windows Command Prompt
        # .\venv\Scripts\Activate.ps1 # On Windows PowerShell
        ```
    *   Your terminal prompt should now indicate that the `venv` environment is active.

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Environment Variables:**
    *   Copy `.env.example` to `.env`:
        ```bash
        cp .env.example .env
        ```
    *   Edit `.env` and fill in your specific details:
        *   `LLM_PROVIDER`: Set to `openai` or `anthropic`.
        *   `LLM_MODEL_NAME`: Specify the *chat completion* model (e.g., `gpt-4o-mini`, `claude-3-haiku-20240307`).
        *   `OPENAI_EMBEDDING_MODEL`: (Optional, defaults to `text-embedding-3-small`) Specify the OpenAI embedding model if needed.
        *   `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`: Add the key for your chosen provider.
        *   **Vector Store Config:**
            *   `DEFAULT_VECTOR_STORE`: Set to `standard` or `semantic` (default: `semantic`).
        *   **Qdrant Config:**
            *   *Local Docker:* Set `QDRANT_HOST=qdrant`, `QDRANT_PORT=6333`. Leave `QDRANT_API_KEY` blank.
            *   *Cloud:* Set `QDRANT_HOST` to your cloud URL, set `QDRANT_API_KEY`.
        *   **AWS S3 Config:** Fill in `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME` (e.g., `askdnd-ai`), `AWS_REGION`. Adjust `AWS_S3_PDF_PREFIX` if needed.
        *   **Flask Config:** Generate a `SECRET_KEY` (e.g., `python -c 'import secrets; print(secrets.token_hex(24))'`), set `APP_PASSWORD`.

6.  **Prepare Data (S3):**
    *   Upload your source PDF files to your configured AWS S3 bucket (`askdnd-ai` or your name) under the specified prefix (default is `source-pdfs/`).
    *   Example using AWS CLI:
        ```bash
        aws s3 cp local/path/to/MyRulebook.pdf s3://askdnd-ai/source-pdfs/MyRulebook.pdf
        ```

7.  **Run the Application:**

    *   **Option A: Fully Dockerized (Recommended)**
        *   Ensure your `.env` is configured for Local Docker Qdrant (`QDRANT_HOST=qdrant`).
        *   Build and run the app and Qdrant containers:
            ```bash
            docker compose -f docker/docker-compose.yml up --build app
            ```
        *   The application will be available at `http://localhost:5000` (or the mapped port).
        *   **First Run or Data Update:** You need to process the PDFs from S3. Open another terminal:
            ```bash
            # List running containers to find the app container name
            docker ps
            # Execute the processing script inside the running app container (use -m flag)
            docker exec -it <your_app_container_name> python -m scripts.manage_vector_stores --reset-history
            ```

    *   **Option B: Flask Dev Server + Docker Qdrant**
        *   Ensure your `.env` is configured for Local Docker Qdrant (`QDRANT_HOST=qdrant`).
        *   Start only the Qdrant container:
            ```bash
            docker compose -f docker/docker-compose.yml up -d qdrant
            ```
        *   **Process PDFs from S3:** Run the management script locally (connects to Docker Qdrant). Ensure your venv is active.
            ```bash
            python -m scripts.manage_vector_stores --reset-history
            ```
            *(Use `--reset-history` for initial setup or full reprocessing. Omit flags for incremental updates based on PDF changes.)*
        *   Run the Flask development server:
            ```bash
            flask run
            ```
        *   Application at `http://localhost:5000`.

    *   **Option C: Flask Dev Server + Qdrant Cloud**
        *   Ensure your `.env` is configured for Qdrant Cloud (Host URL + API Key).
        *   **Process PDFs from S3:** Run the management script locally (connects to Qdrant Cloud). Ensure your venv is active.
            ```bash
            python -m scripts.manage_vector_stores --reset-history
            ```
        *   Run the Flask development server:
            ```bash
            flask run
            ```

8.  **Access:** Open your browser to `http://localhost:5000` (or the appropriate host/port) and log in with the `APP_PASSWORD` set in your `.env` file.

## Deployment (Heroku Example)

1.  **Prerequisites:**
    *   Heroku Account
    *   Qdrant Cloud Cluster URL & API Key.
    *   AWS S3 Bucket configured and populated with PDFs.

2.  **Heroku App Setup:**
    *   Create a Heroku application via the Heroku Dashboard
    *   Connect your GitHub repository to the Heroku app in the "Deploy" tab
    *   Set the GitHub branch to deploy from (e.g., main)

3.  **Configure Heroku Config Vars:**
    *   Set these in the Heroku Dashboard (Settings -> Config Vars)
    *   **Required:**
        *   `LLM_PROVIDER` (e.g., `openai`)
        *   `LLM_MODEL_NAME` (e.g., `gpt-4o-mini`)
        *   `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
        *   `DEFAULT_VECTOR_STORE` (e.g., `standard` or `semantic`)
        *   `QDRANT_HOST` (Your Cloud URL)
        *   `QDRANT_API_KEY`
        *   `AWS_ACCESS_KEY_ID`
        *   `AWS_SECRET_ACCESS_KEY`
        *   `AWS_S3_BUCKET_NAME` (e.g., `askdnd-ai`)
        *   `AWS_REGION`
        *   `SECRET_KEY` (Generate a unique one for production)
        *   `APP_PASSWORD`
    *   **Optional:**
        *   `AWS_S3_PDF_PREFIX` (if different from `source-pdfs/`)
        *   `OPENAI_EMBEDDING_MODEL` (if different from `text-embedding-3-small`)

4.  **Process Data in Cloud:**
    *   You'll need to run a one-off dyno to process the data. This can be done using the Heroku Dashboard:
        *   Go to "More" -> "Run Console" and enter:
          ```bash
          python -m scripts.manage_vector_stores --reset-history
          ```
    *   **Important:** Run this *after* setting all required Config Vars and *before* users access the app. Re-run if PDFs in S3 change (potentially without `--reset-history` for efficiency).

5.  **Deploy:**
    *   Use the "Deploy" tab in the Heroku Dashboard to deploy your app
    *   Click "Deploy Branch" to manually deploy, or enable "Automatic Deploys" for continuous deployment
    *   Heroku will build using `requirements.txt` and run using the `web` process in the `Procfile`
    *   *(Optional)* Adjust dyno type in the "Resources" tab if needed for performance

## Vector Store Approaches

DnDSy implements four different vector store approaches to optimize retrieval:

1. **Standard Approach** (`vector_store/pdf_pages_store.py`)
   * Processes PDF content page-by-page.
   * Embeds the full text of each page using `sentence-transformers` (`all-MiniLM-L6-v2`).
   * Good for maintaining full page context.
   * Stores data in the `dnd_pdf_pages` Qdrant collection.

2. **Semantic Approach** (`vector_store/semantic_store.py`)
   * Chunks content into paragraphs using `langchain`'s `RecursiveCharacterTextSplitter`.
   * Implements cross-page chunking to preserve context across page boundaries.
   * Embeds each chunk using OpenAI's `text-embedding-3-small` model via API.
   * Better for retrieving specific pieces of information.
   * Combines vector similarity search with BM25 keyword search for hybrid retrieval.

3. **Haystack with Qdrant** (`vector_store/haystack/qdrant_store.py`)
   * Uses Haystack framework with Qdrant backend for document storage and retrieval.
   * Leverages Sentence Transformers (`all-MiniLM-L6-v2`) for local embedding generation.
   * Preserves rich document metadata including page context and hierarchical structure.
   * Maintains compatibility with Haystack 2.x API for document filtering and searching.
   * Stores data in the `dnd_haystack` Qdrant collection.
   * Optimized for specialized search queries including monster information lookup.

4. **Haystack with Memory Storage** (`vector_store/haystack/memory_store.py`)
   * Uses Haystack's InMemoryDocumentStore with file persistence.
   * Stores document embeddings in memory and persists to disk as PKL files.
   * Perfect for deployments without Qdrant or for quick local testing.
   * Maintains identical API to the Qdrant implementation for seamless switching.
   * Provides the same functionality with potentially different performance characteristics.
   
Users can switch between these approaches via the UI selector. All approaches are processed and stored in separate collections or persistence files.

## Haystack Processing

To process documents for both Haystack implementations, use the following commands:

```bash
# Process with Qdrant backend
python -m scripts.manage_vector_stores --only-haystack --haystack-type haystack-qdrant

# Process with Memory backend
python -m scripts.manage_vector_stores --only-haystack --haystack-type haystack-memory

# Process all vector stores, including both Haystack implementations
python -m scripts.manage_vector_stores
```

The Memory implementation stores documents in a PKL file in the `data/haystack_store/` directory. This allows for persistence between application restarts without requiring a running Qdrant instance.

## Detailed Data Processing and Indexing Pipeline

The system processes PDFs from S3 to generate two distinct vector databases (collections in Qdrant) using different approaches. Here's a detailed breakdown:

### Orchestration (`scripts/manage_vector_stores.py`)

*   Acts as the main entry point for populating or resetting the vector databases.
*   Handles command-line arguments (`--force-reprocess-images`, `--reset-history`).
*   Connects to Qdrant and deletes existing collections (`dnd_pdf_pages`, `dnd_semantic`) if resetting.
*   Instantiates the `DataProcessor` from the `data_ingestion` package.
*   Calls `DataProcessor.process_all_sources()` to trigger the main pipeline.

### Core Processing (`data_ingestion/processor.py`)

1.  **PDF Discovery & Caching:**
    *   Uses `boto3` to list PDFs from the configured S3 bucket and prefix.
    *   Loads processing history (`pdf_process_history.json`) from S3 (or local file) to track processed PDFs and their hashes.
    *   Compares current PDF hashes (computed via SHA-256) with stored hashes to detect changes.
2.  **PDF Loading & Image Generation:**
    *   Downloads new or changed PDFs from S3.
    *   Uses `PyMuPDF` (fitz) to open PDFs.
    *   If the PDF is new/changed (or forced), generates PNG images for each page and uploads them to a structured path in S3 (`pdf_page_images/`). Skips image generation for unchanged PDFs.
3.  **Structure Analysis (`data_ingestion/structure_analyzer.py`):**
    *   Samples pages from the PDF.
    *   Analyzes font sizes, styles, and formatting using `PyMuPDF`'s dictionary output.
    *   Identifies document hierarchy (up to 6 heading levels).
4.  **Text Extraction & Metadata Collection:**
    *   Iterates through each page of the PDF.
    *   Extracts plain text content.
    *   Uses the `DocumentStructureAnalyzer` to determine the current heading context (e.g., "Chapter > Section > Subsection") for each page.
    *   Collects page text along with rich metadata (S3 source key, filename, page number, total pages, S3 image URL, heading hierarchy) into separate lists for standard and semantic processing.
5.  **Embedding Generation (`embeddings/model_provider.py`):**
    *   **Standard:** Takes the list of full page texts, calls `embed_documents(..., store_type='standard')` which uses `sentence-transformers` (`all-MiniLM-L6-v2`) to generate embeddings in batches.
    *   **Semantic:** Takes the list of page data, calls the semantic store's chunking method (`chunk_document_with_cross_page_context`) to get text chunks. Then calls `embed_documents(chunk_texts, store_type='semantic')` which uses the OpenAI API (`text-embedding-3-small`) to generate embeddings for each chunk.
6.  **Point Creation & Indexing (`vector_store/` modules):**
    *   Constructs Qdrant `PointStruct` objects containing sequential IDs, the generated embedding vectors, the text (page or chunk), and the collected metadata.
    *   Calls the `add_points` method of the appropriate vector store module (`PdfPagesStore` or `SemanticStore`).
    *   The vector store modules handle batch upserting these points into the corresponding Qdrant collection (`dnd_pdf_pages` or `dnd_semantic`).
    *   The `SemanticStore` also updates its internal BM25 retriever during `add_points`.
7.  **History Update:**
    *   Saves the updated `pdf_process_history.json` (with new hashes, timestamps, image URLs) back to S3 and locally.

This refactored pipeline separates concerns: `data_ingestion` orchestrates processing and calls `embeddings` for vector generation, while `vector_store` modules focus solely on Qdrant interaction (storage and retrieval). 