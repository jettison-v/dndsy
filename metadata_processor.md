# Metadata Processor (`metadata_processor.py`)

This module is responsible for generating rich metadata for processed documents (originally PDFs). The goal of this metadata is to enhance the Retrieval-Augmented Generation (RAG) process by providing additional context about the source documents, allowing the system to better rank or filter retrieval results based on the user's query intent.

## Purpose

During data ingestion, simply chunking and embedding document text may not be enough, especially when dealing with multiple documents covering overlapping topics (e.g., the same term like "Druid" appearing as a class in one book and a monster in another). This module aims to:

1.  **Extract Key Information:** Pull out relevant details like title, summary, and keywords from the document content.
2.  **Categorize Documents:** Assign categories based on both a predefined list (constrained) and free-form analysis (automatic).
3.  **Standardize Metadata:** Produce a consistent JSON structure for each document's metadata.
4.  **Store Metadata:** Upload the generated metadata JSON to a designated S3 location for later retrieval.

## Functionality Overview

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

## Metadata Schema

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

## Configuration

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

## Standalone Testing

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

## Future Integration

This module is designed to be integrated into the main data ingestion pipeline (`data_ingestion/processor.py`). The `process_document_for_metadata` function will be called after a PDF's text is extracted, and the resulting metadata will be uploaded via `upload_metadata_to_s3`. 