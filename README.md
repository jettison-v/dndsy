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
*   **Link Extraction:** Extracts internal document links (GOTO) and external web links (URI) from PDFs.
    * For internal links, attempts to capture link text and a snippet of the target page content.
    * Stores extracted link data as structured JSON files in S3 (`extracted_links/`).
*   **Context-Aware Search Results:** Shows proper document structure context in search results:
    * Displays hierarchical paths like "Chapter 5 > Equipment > Weapons"
    * Improves user understanding of where information comes from
    * Maintains the relationship between content and its place in the document
*   **RAG Chatbot:** Answers questions about D&D 2024 rules using provided PDFs as context.
*   **Streaming Responses:** Assistant responses are streamed word-by-word for a real-time feel.
*   **Markdown Formatting:** Assistant responses are formatted using Markdown for enhanced readability (headings, bold, lists, etc.).
*   **Source Attribution:** Shows which document and page number the answer was derived from.
*   **Source Navigation:** Displays source page content as images directly in the interface. Allows navigating between pages of the source document within the side panel.
*   **Context Inspector:** Provides detailed analysis of retrieval results for any query:
    * Visualizes token distribution across context sources
    * Shows exact context pieces sent to the LLM
    * Helps debug and improve retrieval quality
    * Allows testing different retrieval parameters without affecting application settings
*   **Modular Data Processing Pipeline:** Handles PDF parsing, text extraction, image generation, structure analysis, link extraction, embedding generation, and vector store indexing.
*   **AWS S3 Integration:** Handles PDF source files (e.g., `source-pdfs/`), generated page images (`pdf_page_images/`), extracted link data (`extracted_links/`), and processing history (`processing/`) stored in AWS S3.
*   **Abstracted LLM Provider:** Easily switch between LLM providers (e.g., OpenAI, Anthropic) via environment variables.
*   **Cloud Ready:** Designed for deployment with Qdrant Cloud for vector storage and AWS S3 for file storage.
*   **Password Protected:** Simple login system to protect access.
*   **Dockerized:** Includes Docker setup for consistent development and deployment.
*   **Admin Panel:** Provides UI for managing data processing, file uploads, configuration, and monitoring:
    *   **Data Processing:** Trigger PDF processing into selected vector stores (`pages`, `semantic`, `haystack`). Choose cache behavior (`use` or `rebuild`).
    *   **Live Status:** View real-time progress, milestones, and logs during processing runs via a modal window.
    *   **Run History:** View history of processing runs, including start time, duration, parameters, status, and view detailed logs for each run.
    *   **S3 File Management:** List existing PDFs in the source S3 bucket, upload new PDFs (including drag-and-drop).
    *   **Qdrant Management:** View statistics for Qdrant collections, sample points from selected collections.
    *   **Configuration:** View/Update system prompt, tune retrieval parameters (reranking weights, result count), and adjust LLM settings, with comprehensive help text for each option.
    *   **Context Inspector:** Debug tool to analyze what context is retrieved for any query, visualize token distribution, and test retrieval parameters.
    *   **External Links:** Quick links to relevant external services (Railway, Qdrant, S3, etc.).
*   **Responsive Mobile UI:** Fully optimized interface for mobile, tablet, and desktop devices:
    *   **Standardized Breakpoints:** Mobile (≤768px), Tablet (769px-950px), Desktop (>950px).
    *   **Device-Specific Source Panel:** Mobile and tablet use full-screen source panels, desktop uses expandable side panel.
    *   **Touch-Optimized Controls:** Mobile-friendly navigation and zoom controls.
    *   **Consistent Experience:** UI adapts seamlessly across all device sizes.
    *   **Centralized Utilities:** Shared JavaScript utilities in `dnd-utilities.js` for consistent functionality across all platforms.
    *   **Modular Architecture:** Separate mobile implementations in dedicated files with clear separation of concerns.

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
*   **PDF Parsing:** PyMuPDF (`fitz`) for text, image, and link extraction.
*   **Data Ingestion & Processing:** Custom pipeline in `data_ingestion` package using `langchain` for chunking, custom structure analysis, and link extraction.
*   **Frontend:** HTML, CSS, JavaScript (with Marked.js for Markdown rendering)
*   **Cloud Storage:** AWS S3 (Bucket name example: `askdnd-ai`). Stores source PDFs (e.g., `source-pdfs/`), page images (`pdf_page_images/`), extracted links (`extracted_links/`), and processing history (`processing/`).
*   **Deployment:** Docker, Gunicorn, Railway (or similar platform)

## Project Structure

```
dndsy/
├── .env.example             # Example environment variables
├── .gitignore
├── Dockerfile               # For building the application container
├── README.md                # This file
├── app.py                   # Main Flask application entry point
├── config.py                # Centralized configuration management
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
│   ├── css/
│   │   ├── style.css        # Main application styles
│   │   ├── mobile.css       # Mobile-specific responsive styles [DEPRECATED]
│   │   ├── mobile/
│   │   │   ├── mobile-style.css   # Mobile-specific styles
│   │   │   └── mobile-ios-fixes.css # iOS-specific fixes
│   │   └── admin-config.css # Styling for admin configuration panels
│   ├── img/
│   └── js/
│       ├── chat.js          # Main chat interface functionality
│       ├── dnd-utilities.js # Shared utilities for both desktop and mobile
│       ├── marked.min.js    # Markdown rendering
│       ├── source_viewer.js # Source panel management for desktop
│       ├── source_panel.js  # Responsive source panel behavior
│       ├── mobile-ui.js     # Mobile-specific UI enhancements [DEPRECATED]
│       ├── mobile/
│       │   ├── mobile-core.js      # Core mobile functionality
│       │   ├── mobile-chat.js      # Mobile chat interactions
│       │   └── mobile-source-panel.js # Mobile source panel management
│       └── admin.js         # Admin panel functionality
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
            # Use --cache-behavior rebuild for initial setup or full reprocessing
            docker exec -it <your_app_container_name> python -m scripts.manage_vector_stores --cache-behavior rebuild
            # For incremental updates (use cache)
            # docker exec -it <your_app_container_name> python -m scripts.manage_vector_stores --cache-behavior use 
            ```

    *   **Option B: Flask Dev Server + Docker Qdrant**
        *   Ensure your `.env` is configured for Local Docker Qdrant (`QDRANT_HOST=qdrant`).
        *   Start only the Qdrant container:
            ```bash
            docker compose -f docker/docker-compose.yml up -d qdrant
            ```
        *   **Process PDFs from S3:** Run the management script locally (connects to Docker Qdrant). Ensure your venv is active.
            ```bash
            # Use --cache-behavior rebuild for initial setup or full reprocessing
            python -m scripts.manage_vector_stores --cache-behavior rebuild
            # For incremental updates (use cache, default)
            # python -m scripts.manage_vector_stores --cache-behavior use 
            # Or simply (uses defaults: --store all --cache-behavior use)
            # python -m scripts.manage_vector_stores
            ```
        *   Run the Flask development server:
            ```bash
            flask run
            ```
        *   Application at `http://localhost:5000`.
        *   *Note:* For local mobile testing with specific session configurations, you can alternatively run `python run_mobile_test_server.py` which starts the server on port 5001 and makes it accessible on your local network.

    *   **Option C: Flask Dev Server + Qdrant Cloud**
        *   Ensure your `.env` is configured for Qdrant Cloud (Host URL + API Key).
        *   **Process PDFs from S3:** Run the management script locally (connects to Qdrant Cloud). Ensure your venv is active.
            ```bash
            # Use --cache-behavior rebuild for initial setup or full reprocessing
            python -m scripts.manage_vector_stores --cache-behavior rebuild
            # For incremental updates (use cache, default)
            # python -m scripts.manage_vector_stores
            ```
        *   Run the Flask development server:
            ```bash
            flask run
            ```
        *   *Note:* For local mobile testing with specific session configurations, you can alternatively run `python run_mobile_test_server.py` which starts the server on port 5001 and makes it accessible on your local network.

8.  **Access:** Open your browser to `http://localhost:5000` (or the appropriate host/port) and log in with the `APP_PASSWORD` set in your `.env` file.

## Deployment (Railway Example)

1.  **Prerequisites:**
    *   Railway Account
    *   Qdrant Cloud Cluster URL & API Key.
    *   AWS S3 Bucket configured and populated with PDFs.

2.  **Railway Project Setup:**
    *   Create a new Railway project from your GitHub repository.
    *   Railway will automatically detect the `Dockerfile` or use Nixpacks to build and deploy.

3.  **Configure Railway Environment Variables:**
    *   Set these in the Railway project settings (Variables tab).
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

4.  **Process Data in Cloud (One-Time Task or via Admin UI):**
    *   **Option A (Railway Run Command - Manual):** You may need to run the processing script manually the first time or after major PDF updates. Use Railway's `railway run` command locally (requires Railway CLI) or trigger it through a deploy script if configured:
      ```bash
      # Example using Railway CLI (ensure environment variables are accessible)
      # railway run python -m scripts.manage_vector_stores --cache-behavior rebuild
      # railway run python -m scripts.manage_vector_stores --cache-behavior use # For updates
      ```
    *   **Option B (Admin Panel):** The recommended way is to deploy the application first, then use the Admin Panel's "Data Processing" feature to trigger the indexing job (`scripts.manage_vector_stores`). This avoids needing the Railway CLI for this task.
    *   **Important:** Ensure data processing completes *after* setting all required environment variables and *before* users expect full functionality.

5.  **Deploy & Access:**
    *   Railway automatically deploys upon code pushes to the connected branch.
    *   Monitor the deployment logs in the Railway dashboard.
    *   Once deployed, access the application via the public URL provided by Railway.
    *   Railway uses the `Procfile` or the `CMD`/`ENTRYPOINT` in your `Dockerfile` to start the web server (Gunicorn).

## Metadata Processing Module (`metadata_processor.py`)

This module is responsible for generating rich metadata for processed documents (originally PDFs). The goal of this metadata is to enhance the Retrieval-Augmented Generation (RAG) process by providing additional context about the source documents, allowing the system to better rank or filter retrieval results based on the user's query intent.

### Purpose

During data ingestion, simply chunking and embedding document text may not be enough, especially when dealing with multiple documents covering overlapping topics (e.g., the same term like "Druid" appearing as a class in one book and a monster in another). This module aims to:

1.  **Extract Key Information:** Pull out relevant details like title, summary, and keywords from the document content.
2.  **Categorize Documents:** Assign categories based on both a predefined list (constrained) and free-form analysis (automatic).
3.  **Standardize Metadata:** Produce a consistent JSON structure for each document's metadata.
4.  **Store Metadata:** Upload the generated metadata JSON to a designated S3 location for later retrieval.

### Functionality Overview

1.  **Initialization:** Requires AWS S3 credentials (`AWS_S3_BUCKET_NAME`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) and LLM provider credentials (e.g., `OPENAI_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL_NAME`) to be set as environment variables. It initializes clients for S3 and the configured LLM provider.
2.  **Main Function (`process_document_for_metadata`):**
    *   Takes the raw PDF content (optional, for ID generation), extracted text, filename, S3 path, and a list of available categories (from `config.py`) as input.
    *   Generates a unique `document_id` (currently SHA256 hash of S3 path or content).
    *   Calls helper functions to populate metadata fields.
    *   Returns the complete metadata dictionary.
3.  **Metadata Extraction Functions:**
    *   `determine_constrained_category`: Uses the LLM to classify the document text and select the single best-fitting category from the `available_categories` list provided.
    *   `determine_automatic_category`: Uses the LLM to analyze the document text and generate a concise, descriptive category name freely (without constraints).
    *   `extract_source_book_title`: Attempts to extract the title using regex (looking for `Title: ...`) and fallback logic (checking the first few non-empty lines).
    *   `generate_summary`: Uses the LLM to create a brief (2-4 sentence) summary of the document text.
    *   `extract_keywords`: Uses the LLM to identify and extract relevant keywords and key phrases as a comma-separated list.
4.  **S3 Interaction:**
    *   `upload_metadata_to_s3`: Takes the generated metadata dictionary and uploads it as a JSON file to the configured S3 bucket under the `metadata/` prefix (e.g., `s3://your-bucket/metadata/<document_id>.json`).
    *   `get_metadata_from_s3`: Retrieves a specific metadata JSON file from S3 based on its `document_id`.

### Metadata Schema

The generated metadata JSON follows this structure:

```json
{
  "document_id": "unique_identifier_for_the_document",
  "original_filename": "source_pdf_filename.pdf",
  "s3_pdf_path": "s3://your-raw-pdf-bucket/path/to/document.pdf",
  "constrained_category": "Category chosen from predefined list",
  "automatic_category": "Category determined freely by LLM",
  "source_book_title": "Extracted Title | null",
  "summary": "LLM-generated summary of the document.",
  "keywords": ["keyword1", "keyword2", "topic3"],
  "processing_timestamp": "ISO_8601_timestamp"
}
```

*   `constrained_category`: The best fit from the `PREDEFINED_CATEGORIES_LIST` in `config.py`, chosen by the LLM.
*   `automatic_category`: A descriptive category generated freely by the LLM.

### Configuration

This module relies on environment variables for configuration:

*   **S3 Configuration:**
    *   `AWS_S3_BUCKET_NAME`: Name of the S3 bucket to store metadata files (falls back to `your-metadata-bucket-name-fallback` if not set).
    *   `AWS_ACCESS_KEY_ID`: Your AWS Access Key ID.
    *   `AWS_SECRET_ACCESS_KEY`: Your AWS Secret Access Key.
    *   `AWS_REGION`: The AWS Region where the bucket resides (defaults to `us-east-1` if not set).
*   **LLM Configuration:**
    *   `LLM_PROVIDER`: Specifies the LLM provider (e.g., `openai`, `anthropic`). Used by `llm_providers.get_llm_client()`.
    *   `LLM_MODEL_NAME`: Specifies the model to use for generation tasks. Used by `llm_providers.get_llm_client()`.
    *   `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` (etc.): API key for the chosen provider.

### Standalone Testing

The module can be run directly for testing using the `if __name__ == "__main__":` block.

```bash
python metadata_processor.py
```

This test block:

*   Uses mock document content and S3 path.
*   Uses a mock list of available categories.
*   Calls `process_document_for_metadata`.
*   Prints the generated metadata JSON to the console.
*   **Optionally** attempts S3 upload/download if `MOCK_S3` is set to `True` within the script (requires valid AWS credentials and bucket configuration).

You can modify the mock data or load real text content within this block for more specific testing.

### Future Integration

This module is designed to be integrated into the main data ingestion pipeline (`data_ingestion/processor.py`). The `process_document_for_metadata` function will be called after a PDF's text is extracted, and the resulting metadata will be uploaded via `upload_metadata_to_s3`.

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

To process documents specifically for the Haystack implementations, use the `--store` flag:

```bash
# Process ONLY the Haystack Qdrant store (using cache by default)
python -m scripts.manage_vector_stores --store haystack-qdrant

# Process ONLY the Haystack Memory store (using cache by default)
python -m scripts.manage_vector_stores --store haystack-memory

# Process BOTH Haystack stores sequentially (Qdrant then Memory, using cache by default)
python -m scripts.manage_vector_stores --store haystack

# Rebuild cache and process ONLY the Haystack Qdrant store
python -m scripts.manage_vector_stores --store haystack-qdrant --cache-behavior rebuild
```

The Memory implementation stores documents in a PKL file in the `data/haystack_store/` directory. This allows for persistence between application restarts without requiring a running Qdrant instance.

## Detailed Data Processing and Indexing Pipeline

The system processes PDFs from S3 to generate vector data for the selected stores using a unified pipeline.

### Orchestration (`scripts/manage_vector_stores.py`)

*   Acts as the main entry point for populating or resetting the vector databases.
*   Handles command-line arguments:
    *   `--store`: Selects target store(s) (`all`, `pages`, `semantic`, `haystack`, `haystack-qdrant`, `haystack-memory`).
    *   `--cache-behavior`: Controls caching (`use` or `rebuild`).
    *   `--s3-pdf-prefix` (Optional): Overrides the S3 source PDF prefix from `.env`, useful for testing.
*   If `cache-behavior` is `rebuild`, connects to Qdrant/handles local files to delete existing target collections/files and resets processing history.
*   Instantiates the `DataProcessor` *once* (or twice if processing both Haystack types), configuring it based on flags and passing the S3 prefix.
*   Calls `DataProcessor.process_all_sources()` to trigger the main pipeline.

### Core Processing (`data_ingestion/processor.py`)

1.  **PDF Discovery & Caching Check:**
    *   Lists PDFs from the configured S3 bucket/prefix.
    *   Loads processing history (`pdf_process_history.json`) from S3 or local file.
    *   For each PDF, computes its hash.
    *   Compares hash to history and checks `cache_behavior` to determine if processing is needed for each target store.
    *   Determines if image generation is required (only if `cache_behavior=rebuild` or PDF is new/changed).
2.  **PDF Loading & Image Generation:**
    *   Downloads the PDF from S3.
    *   If image generation is required:
        *   Deletes any old images for the PDF from S3.
        *   Uses `PyMuPDF` (fitz) to generate PNG images for each page.
        *   Uploads images to a structured path in S3 (`pdf_page_images/`).
        *   Updates history with new image URLs.
    *   If image generation is skipped, retrieves existing image URLs from history.
3.  **Structure Analysis (`data_ingestion/structure_analyzer.py`):**
    *   Analyzes font sizes/styles using `PyMuPDF` on sample pages to identify document hierarchy.
4.  **Text Extraction & Metadata Collection:**
    *   Iterates through each page of the PDF.
    *   Extracts plain text.
    *   Uses the `DocumentStructureAnalyzer` to determine heading context.
    *   Collects page text along with rich metadata (S3 source key, filename, page number, total pages, S3 image URL, heading hierarchy, etc.).
5.  **Sequential Processing for Target Stores:**
    *   For the *current PDF*, proceeds based on which stores (`pages`, `semantic`, `haystack`) are targeted and not skipped due to cache:
        *   **Pages Store:** If processing `pages`, embeds full page texts using `sentence-transformers` (`all-MiniLM-L6-v2`) via `embeddings/model_provider.py`. Creates Qdrant points and adds them to the `PdfPagesStore` (`dnd_pdf_pages` collection).
        *   **Semantic Store:** If processing `semantic`, chunks page data (with cross-page context) using `