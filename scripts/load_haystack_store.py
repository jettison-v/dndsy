#!/usr/bin/env python3
import os
import sys
import logging
import json
from pathlib import Path

# Add the parent directory to sys.path to import modules
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.append(parent_dir)

from vector_store import get_vector_store
from data_ingestion.processor import DataProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Load documents into the haystack store."""
    logger.info("Starting to load documents into haystack store")
    
    # Initialize the haystack store
    haystack_store = get_vector_store("haystack")
    
    # Check if there are already documents in the store
    try:
        doc_count = haystack_store.document_store.get_document_count()
        if doc_count > 0:
            logger.info(f"Haystack store already has {doc_count} documents")
            return
    except Exception as e:
        logger.warning(f"Could not check document count: {e}")
        # Continue with loading
    
    # Get the PDF history file path
    history_file = os.path.join(parent_dir, "pdf_process_history.json")
    
    if not os.path.exists(history_file):
        logger.error(f"PDF process history file not found: {history_file}")
        logger.error("Please run manage_vector_stores.py first to process the PDFs")
        return
    
    # Load the process history
    with open(history_file, 'r') as f:
        process_history = json.load(f)
    
    # Initialize the processor to access chunking methods
    processor = DataProcessor(
        process_standard=False,
        process_semantic=False,
        process_haystack=True,
        force_processing=True
    )
    
    # Process each PDF for haystack
    total_chunks = 0
    for pdf_file, pdf_info in process_history.items():
        try:
            logger.info(f"Processing {pdf_file} for haystack store")
            
            # Call the processor's method for haystack processing
            pdf_hash = pdf_info.get("hash", "")
            semantic_page_data = processor._get_semantic_data(pdf_info)
            
            processor._process_pdf_for_haystack(pdf_file, pdf_hash, semantic_page_data, pdf_info)
            
            # Get the processed flag for this PDF
            processed_stores = pdf_info.get("processed_stores", {})
            if "haystack" in processed_stores:
                logger.info(f"Successfully processed {pdf_file} for haystack store")
                total_chunks += 1
            else:
                logger.warning(f"Failed to process {pdf_file} for haystack store")
            
        except Exception as e:
            logger.error(f"Error processing {pdf_file} for haystack: {e}", exc_info=True)
    
    logger.info(f"Finished loading documents. Added chunks for {total_chunks} PDFs to haystack store")

if __name__ == "__main__":
    main() 