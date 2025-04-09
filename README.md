# DnDSy - D&D 2024 Rules Assistant

DnDSy is a web application that acts as an intelligent assistant for the 2024 Dungeons & Dragons ruleset (unofficially 5.5e). It uses Retrieval-Augmented Generation (RAG) to answer user questions based on official PDF source materials.

## Features

*   **Multiple RAG Approaches:** Choose between different vector store approaches for optimal retrieval:
    * **Standard:** Process PDFs page-by-page for broader context.
    * **Semantic:** Chunk content into paragraphs for more precise, semantic search.
*   **RAG Chatbot:** Answers questions about D&D 2024 rules using provided PDFs as context.
*   **Streaming Responses:** Assistant responses are streamed word-by-word for a real-time feel.
*   **Markdown Formatting:** Assistant responses are formatted using Markdown for enhanced readability (headings, bold, lists, etc.).
*   **Source Attribution:** Shows which document and page number the answer was derived from.
*   **Source Navigation:** Displays source page content as images directly in the interface. Allows navigating between pages of the source document within the side panel.
*   **PDF Processing:** Automatically processes PDF documents, extracts text, generates page images, and indexes content for semantic search.
*   **AWS S3 Integration:** Handles PDF source files and generated page images stored in AWS S3.
*   **Abstracted LLM Provider:** Easily switch between LLM providers (e.g., OpenAI, Anthropic) via environment variables.
*   **Cloud Ready:** Designed for deployment with Qdrant Cloud for vector storage and AWS S3 for file storage.
*   **Password Protected:** Simple login system to protect access.
*   **Dockerized:** Includes Docker setup for consistent development and deployment.

## Technology Stack

*   **Backend:** Python, Flask
*   **Vector Database:** Qdrant (Cloud recommended for deployment)
*   **LLM:** Pluggable via `llm_providers` (e.g., OpenAI, Anthropic)
*   **Embeddings:** Sentence Transformers (`all-MiniLM-L6-v2` for standard, `paraphrase-MiniLM-L6-v2` for semantic)
*   **PDF Parsing:** PyMuPDF (`fitz`)
*   **NLP Processing:** spaCy, NLTK, langchain for semantic chunking
*   **Frontend:** HTML, CSS, JavaScript (with Marked.js for Markdown rendering)
*   **Cloud Storage:** AWS S3
*   **Deployment:** Docker, Gunicorn, Heroku (or similar platform)

## Project Structure

```
dndsy/
├── .env.example             # Example environment variables
├── .gitignore
├── Dockerfile               # For building the application container
├── README.md                # This file
├── app.py                   # Main Flask application entry point
├── llm.py                   # Handles RAG logic, LLM calls, context processing
├── llm_providers/           # Abstraction layer for different LLM APIs
│   ├── __init__.py
│   ├── anthropic_client.py
│   ├── base_llm.py
│   └── openai_client.py
├── requirements.txt         # Python dependencies
├── static/
│   ├── css/style.css        # Main stylesheet
│   ├── img/                   # Static images (e.g., background)
│   └── js/
│       ├── chat.js            # Frontend JavaScript for chat interaction, SSE
│       ├── marked.min.js      # Markdown rendering library
│       └── source_viewer.js   # JS for source panel interaction
├── templates/
│   ├── index.html           # Main chat interface template
│   └── login.html           # Login page template
├── vector_store/
│   ├── __init__.py          # Vector store factory
│   ├── qdrant_store.py      # Standard vector store implementation
│   └── semantic_store.py    # Semantic vector store implementation
├── scripts/
│   ├── process_pdfs_s3.py   # Script to process PDFs from S3
│   ├── reset_and_process.py # Helper to clear DB and reprocess
│   └── setup_env.py         # Helper to create initial .env file
└── docker/
    └── docker-compose.yml   # Docker Compose for local development (app + Qdrant)
├── logs/                   # Centralized directory for log files
│   ├── data_processing.log # Data processing logs
│   ├── reset_script.log    # Vector store reset logs
│   └── fix_semantic.log    # Semantic fix logs
├── debug/                  # Scripts for debugging and testing
│   ├── check_qdrant.py     # Script to check Qdrant collection stats
│   └── fix_semantic.py     # Script to fix semantic collection

```

## Local Development Setup

1.  **Prerequisites:**
    *   Python 3.11+
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
    *   Create and activate a virtual environment:
        ```bash
        python -m venv venv
        source venv/bin/activate  # On Windows use `venv\Scripts\activate`
        ```

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
        *   `LLM_MODEL_NAME`: Specify the model (e.g., `gpt-4o-mini`, `claude-3-haiku-20240307`).
        *   `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`: Add the key for your chosen provider.
        *   **Vector Store Config:**
            *   `DEFAULT_VECTOR_STORE`: Set to `standard` or `semantic` (default: `standard`).
        *   **Qdrant Config:**
            *   *Local Docker:* Set `QDRANT_HOST=qdrant`, `QDRANT_PORT=6333`. Leave `QDRANT_API_KEY` blank.
            *   *Cloud:* Set `QDRANT_HOST` to your cloud URL, set `QDRANT_API_KEY`.
        *   **AWS S3 Config:** Fill in `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`, `AWS_REGION`. Adjust `AWS_S3_PDF_PREFIX` if needed.
        *   **Flask Config:** Generate a `SECRET_KEY` (e.g., `python -c 'import secrets; print(secrets.token_hex(24))'`), set `APP_PASSWORD`.

6.  **Prepare Data (S3):**
    *   Upload your source PDF files to your configured AWS S3 bucket under the specified prefix (default is `source-pdfs/`).
    *   Example using AWS CLI:
        ```bash
        aws s3 cp local/path/to/MyRulebook.pdf s3://YOUR_BUCKET_NAME/source-pdfs/MyRulebook.pdf
        ```

7.  **Run the Application:**

    *   **Option A: Fully Dockerized (Recommended)**
        *   Ensure your `.env` is configured for Local Docker Qdrant (`QDRANT_HOST=qdrant`).
        *   Build and run the app and Qdrant containers:
            ```bash
            docker compose -f docker/docker-compose.yml up --build app
            ```
        *   The application will be available at `http://localhost:5000` (or the mapped port).
        *   First Run Only: You need to process the PDFs from S3. Open another terminal:
            ```bash
            # List running containers to find the app container name
            docker ps
            # Execute the processing script inside the running app container
            docker exec -it <your_app_container_name> python scripts/reset_and_process.py
            ```

    *   **Option B: Flask Dev Server + Docker Qdrant**
        *   Ensure your `.env` is configured for Local Docker Qdrant (`QDRANT_HOST=qdrant`).
        *   Start only the Qdrant container:
            ```bash
            docker compose -f docker/docker-compose.yml up -d qdrant
            ```
        *   Process PDFs from S3 (runs locally, connects to Docker Qdrant):
            ```bash
            python scripts/reset_and_process.py
            ```
        *   Run the Flask development server:
            ```bash
            flask run
            ```
        *   Application at `http://localhost:5000`.

    *   **Option C: Flask Dev Server + Qdrant Cloud**
        *   Ensure your `.env` is configured for Qdrant Cloud (Host URL + API Key).
        *   Process PDFs from S3 (runs locally, connects to Qdrant Cloud):
            ```bash
            python scripts/reset_and_process.py
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
        *   `AWS_S3_BUCKET_NAME`
        *   `AWS_REGION`
        *   `SECRET_KEY` (Generate a unique one for production)
        *   `APP_PASSWORD`
    *   **Optional:**
        *   `AWS_S3_PDF_PREFIX` (if different from `source-pdfs/`)

4.  **Process Data in Cloud:**
    *   You'll need to run a one-off dyno to process the data. This can be done using the Heroku Dashboard:
        *   Go to "More" -> "Run Console" and enter: `python scripts/reset_and_process.py`
    *   **Important:** Run this *after* setting all required Config Vars and *before* users access the app. Re-run if PDFs in S3 change.

5.  **Deploy:**
    *   Use the "Deploy" tab in the Heroku Dashboard to deploy your app
    *   Click "Deploy Branch" to manually deploy, or enable "Automatic Deploys" for continuous deployment
    *   Heroku will build using `requirements.txt` and run using the `web` process in the `Procfile`
    *   *(Optional)* Adjust dyno type in the "Resources" tab if needed for performance

## Vector Store Approaches

DnDSy implements two different vector store approaches to optimize retrieval:

1. **Standard Approach**
   * Processes PDF content page-by-page
   * Uses `all-MiniLM-L6-v2` embedding model
   * Good for maintaining full page context
   * Default approach

2. **Semantic Approach**
   * Chunks content into paragraphs
   * Uses `paraphrase-MiniLM-L6-v2` embedding model
   * Better for retrieving specific pieces of information
   * More precise, especially for detailed rules questions
   
Users can switch between these two approaches via the UI selector. Both approaches are processed and stored in separate Qdrant collections. 