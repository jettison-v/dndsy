# Scripts Directory

This directory contains utility scripts for managing and maintaining the DnDSy application.

## Available Scripts

### Vector Store Management

**manage_vector_stores.py**
```bash
# Reset and process all vector stores
python scripts/manage_vector_stores.py

# Only process Haystack with Qdrant implementation
python scripts/manage_vector_stores.py --only-haystack --haystack-type haystack-qdrant

# Only process Haystack with Memory implementation
python scripts/manage_vector_stores.py --only-haystack --haystack-type haystack-memory

# Force reprocessing of documents even if they haven't changed
python scripts/manage_vector_stores.py --force-reprocess-images

# Reset processing history and reprocess everything
python scripts/manage_vector_stores.py --reset-history
```

**load_haystack_store.py**
```bash
# Load documents into the Haystack store
python scripts/load_haystack_store.py
```

### Environment Setup

**setup_env.py**
```bash
# Configure the application environment
python scripts/setup_env.py
```

## Running Scripts

All scripts should be run from the project root directory to ensure correct module imports and path resolution. 