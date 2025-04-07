# DnDSy - D&D 2024 Rules Assistant

DnDSy is a web application that acts as an intelligent assistant for the 2024 Dungeons & Dragons ruleset (unofficially 5.5e). It uses Retrieval-Augmented Generation (RAG) to answer user questions based on official PDF source materials.

## Features

*   **RAG Chatbot:** Answers questions about D&D 2024 rules using provided PDFs as context.
*   **Source Attribution:** Shows which document and page number the answer was derived from.
*   **Source Navigation:** Displays source page content as images directly in the interface. Allows navigating between pages of the source document within the side panel.
*   **PDF Processing:** Automatically processes PDF documents, extracts text, generates page images, and indexes content for semantic search.
*   **Cloud Ready:** Designed for deployment with Qdrant Cloud for vector storage.
*   **Password Protected:** Simple login system to protect access.

## Technology Stack

*   **Backend:** Python, Flask
*   **Vector Database:** Qdrant (Cloud recommended for deployment)
*   **LLM:** OpenAI API (GPT-3.5 Turbo / GPT-4)
*   **Embeddings:** Sentence Transformers (`all-MiniLM-L6-v2`)
*   **PDF Parsing:** PyMuPDF (`fitz`)
*   **Frontend:** HTML, CSS, JavaScript
*   **Deployment:** Docker, Gunicorn, Heroku (or similar platform)

## Local Development Setup

1.  **Clone Repository:**
    ```bash
    git clone <your-repo-url>
    cd dndsy
    ```

2.  **Python Environment:**
    *   Ensure you have Python 3.11+ installed.
    *   It's recommended to use a virtual environment:
        ```bash
        python -m venv venv
        source venv/bin/activate  # On Windows use `venv\\Scripts\\activate`
        ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: This installs the CPU version of PyTorch by default, suitable for local development without a GPU)*

4.  **Environment Variables:**
    *   Create a `.env` file in the project root. You can use the helper script:
        ```bash
        python setup_env.py
        ```
        This will prompt for your OpenAI key and create a basic `.env` file.
    *   Manually add the following to your `.env` file:
        ```dotenv
        OPENAI_API_KEY=<Your OpenAI API Key>
        QDRANT_HOST=localhost # For local Qdrant via Docker
        QDRANT_PORT=6333      # For local Qdrant via Docker
        SECRET_KEY=<Generate a strong secret key, e.g., using python -c 'import secrets; print(secrets.token_hex(24))'>
        APP_PASSWORD=<Choose a password for the login page>
        # Optional: Set for development mode features if needed
        # FLASK_ENV=development
        # FLASK_DEBUG=1
        ```

5.  **Prepare Data (S3):**
    *   Obtain your source PDF files.
    *   Upload these PDFs to your configured AWS S3 bucket under the specified prefix (default is `source-pdfs/`). You can use the AWS Console or AWS CLI.
    *   Example using AWS CLI:
        ```bash
        # Make sure AWS CLI is configured (aws configure)
        aws s3 cp local/path/to/MyRulebook.pdf s3://YOUR_BUCKET_NAME/source-pdfs/MyRulebook.pdf
        # Upload a whole directory recursively
        aws s3 cp local/path/to/pdf_folder/ s3://YOUR_BUCKET_NAME/source-pdfs/ --recursive
        ```

6.  **Run the Application:**
    *   **Using Docker (Recommended for consistency):**
        ```bash
        docker compose up --build app # Build and start the app service (and Qdrant if not running)
        ```
        The app will be available at `http://localhost:5001`.
    *   **Using Flask Development Server (Requires local Qdrant running):**
        ```bash
        # Ensure Qdrant is running via 'docker compose up -d qdrant'
        # Ensure environment variables are set (either via .env and loaded, or exported)
        python app.py
        ```

## Deployment (Heroku Example)

1.  **Qdrant Cloud:**
    *   Set up a cluster on [Qdrant Cloud](https://cloud.qdrant.io/). The free tier is suitable for starting.
    *   Obtain your Cluster URL and generate an API Key.

2.  **Heroku Setup:**
    *   Create a Heroku application.
    *   Connect your GitHub repository (main branch) for deployment.
    *   Configure Heroku **Config Vars** (in app settings -> "Config Vars"):
        *   `OPENAI_API_KEY`: Your OpenAI API Key.
        *   `QDRANT_HOST`: Your Qdrant Cloud Cluster URL.
        *   `QDRANT_API_KEY`: Your Qdrant Cloud API Key.
        *   `SECRET_KEY`: A unique, randomly generated secret key.
        *   `APP_PASSWORD`: The password you want for the deployed application login.
        *   *(Optional)* `PYTHON_VERSION`: e.g., `3.11` (Consider using `.python-version` file instead of `runtime.txt`)

3.  **Populate Cloud Data:**
    *   Ensure your source PDFs have been uploaded to the correct prefix in your S3 bucket (see Local Setup Step 5).
    *   Ensure your Heroku app has the necessary Config Vars set (Qdrant Cloud details, OpenAI Key, AWS Credentials, `AWS_S3_BUCKET_NAME`, `AWS_S3_PDF_PREFIX` if not using default).
    *   Run the processing script using a one-off Heroku dyno. This will download PDFs from S3, generate images, upload images to S3, and populate Qdrant Cloud.
        ```bash
        heroku run python reset_and_process.py -a YOUR_APP_NAME
        ```
    *   This step needs to be repeated whenever the source PDFs in S3 change.

4.  **Deploy:**
    *   Push your code to the branch connected to Heroku (e.g., `main`).
    *   Trigger a deployment on Heroku (either automatically on push or manually). Heroku will use the `Procfile` to run the application using `gunicorn`. 