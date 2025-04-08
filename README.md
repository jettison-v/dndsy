# DnDSy - D&D 2024 Rules Assistant

DnDSy is a web application that acts as an intelligent assistant for the 2024 Dungeons & Dragons ruleset (unofficially 5.5e). It uses Retrieval-Augmented Generation (RAG) to answer user questions based on official PDF source materials.

## Features

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
*   **Embeddings:** Sentence Transformers (`all-MiniLM-L6-v2`)
*   **PDF Parsing:** PyMuPDF (`fitz`)
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
│   ├── __init__.py
│   ├── base_store.py
│   └── qdrant_store.py      # Qdrant vector store implementation
├── scripts/
│   ├── process_pdfs_s3.py   # Script to process PDFs from S3
│   ├── reset_and_process.py # Helper to clear DB and reprocess
│   └── setup_env.py         # Helper to create initial .env file
└── docker/
    └── docker-compose.yml   # Docker Compose for local development (app + Qdrant)

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
    *   Heroku Account & Heroku CLI installed.
    *   Qdrant Cloud Cluster URL & API Key.
    *   AWS S3 Bucket configured and populated with PDFs.

2.  **Heroku App Setup:**
    *   Create a Heroku application: `heroku create your-app-name`
    *   Set the buildpack to Python: `heroku buildpacks:set heroku/python -a your-app-name`
    *   Connect your GitHub repository for deployment or use `git push heroku main`.

3.  **Configure Heroku Config Vars:**
    *   Set these in the Heroku Dashboard (Settings -> Config Vars) or via CLI.
    *   **Required:**
        *   `LLM_PROVIDER` (e.g., `openai`)
        *   `LLM_MODEL_NAME` (e.g., `gpt-4o-mini`)
        *   `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
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
    *   Run the processing script as a one-off dyno on Heroku. This connects to S3 and Qdrant Cloud using the Config Vars.
        ```bash
        heroku run python scripts/reset_and_process.py -a your-app-name
        ```
    *   **Important:** Run this *after* setting all required Config Vars and *before* users access the app. Re-run if PDFs in S3 change.

5.  **Deploy:**
    *   Push your latest code to the branch Heroku monitors (e.g., `main`).
    *   `git push heroku main` (if using Git deployment).
    *   Heroku will build using `requirements.txt` and run using the `web` process in the `Procfile`.
    *   *(Optional)* Scale your dynos if needed (e.g., `heroku ps:scale web=1:standard-1x -a your-app-name`). Check memory usage in Metrics.

## Notes

*   **Token Counting:** Current token counting uses `tiktoken`, which is specific to OpenAI models. If using other providers extensively, consider a more generic tokenizer or provider-specific methods.
*   **Memory Usage:** RAG applications can be memory-intensive due to holding context. Monitor memory usage, especially during PDF processing and chat interactions. Consider upgrading dyno resources if needed.
*   **Error Handling:** Basic error handling is included, but can be enhanced for production environments. 