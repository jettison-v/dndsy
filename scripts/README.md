# Scripts Directory

This directory contains utility scripts for managing and maintaining the DnDSy application.

## Available Scripts

### Vector Store Management

**manage_vector_stores.py**

This script handles the processing of source PDFs from S3 into the various vector stores used by the application. It manages caching, image generation, chunking, embedding, and indexing.

**Usage:**

```bash
# Process ALL stores ('pages', 'semantic', 'haystack-qdrant', 'haystack-memory') 
# using the cache (only processes new/changed PDFs)
python -m scripts.manage_vector_stores --store all --cache-behavior use
# (Defaults: --store=all --cache-behavior=use, so the above is equivalent to:)
# python -m scripts.manage_vector_stores

# Process ONLY the 'pages' store, using the cache
python -m scripts.manage_vector_stores --store pages --cache-behavior use

# Process ONLY the 'semantic' store, using the cache
python -m scripts.manage_vector_stores --store semantic --cache-behavior use

# Process ONLY the 'haystack-qdrant' store, using the cache
python -m scripts.manage_vector_stores --store haystack-qdrant --cache-behavior use

# Process ONLY the 'haystack-memory' store, using the cache
python -m scripts.manage_vector_stores --store haystack-memory --cache-behavior use

# Process BOTH Haystack stores (qdrant then memory), using the cache
python -m scripts.manage_vector_stores --store haystack --cache-behavior use

# REBUILD cache and process ALL stores (clears history, clears stores, processes all PDFs)
python -m scripts.manage_vector_stores --store all --cache-behavior rebuild

# REBUILD cache and process ONLY the 'semantic' store
python -m scripts.manage_vector_stores --store semantic --cache-behavior rebuild
```

**Flags:**

*   `--store`: Specifies which vector store(s) to process.
    *   Choices: `all` (default), `pages`, `semantic`, `haystack`, `haystack-qdrant`, `haystack-memory`.
    *   `haystack` processes both Qdrant and Memory implementations sequentially.
*   `--cache-behavior`: Controls how the processing history and existing data are handled.
    *   Choices: `use` (default), `rebuild`.
    *   `use`: Checks the processing history (`pdf_process_history.json`) and only processes PDFs that are new or have changed since the last run for the target store(s). Skips image generation for unchanged PDFs.
    *   `rebuild`: Deletes the processing history, clears the target vector store(s), and processes *all* PDFs from S3 as if they were new. Regenerates all page images.
*   `--s3-pdf-prefix`: (Optional) Specifies an alternative S3 prefix for source PDFs.
    *   Example: `--s3-pdf-prefix test-pdfs/`
    *   If provided, overrides the `AWS_S3_PDF_PREFIX` setting from the `.env` file. Useful for testing with a subset of documents.

**load_haystack_store.py**

*Deprecated:* This script was used in earlier versions to specifically load documents into a Haystack store. This functionality is now integrated into `manage_vector_stores.py` using the `--store haystack`, `--store haystack-qdrant`, or `--store haystack-memory` flags. This script is no longer needed and may be removed in the future.

**setup_env.py**

This is a helper script to interactively create an initial `.env` file for local development. It prompts the user for their OpenAI API Key and writes it to `.env`, along with default settings for connecting to a local Qdrant instance (`QDRANT_HOST=localhost`, `QDRANT_PORT=6333`).

**Usage:**

```bash
python scripts/setup_env.py
```

If a `.env` file already exists, it will ask if you want to overwrite it.