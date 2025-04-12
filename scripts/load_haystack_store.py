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
        doc_count = haystack_store.document_store.count_documents()
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
        force_processing=True, 
        process_standard=False,
        process_semantic=False,
        process_haystack=True
    )
    
    # Process each PDF for haystack
    total_chunks = 0
    for pdf_file, pdf_info in process_history.items():
        try:
            logger.info(f"Processing {pdf_file} for haystack store")
            
            # Get the PDF text and metadata
            source_path = os.path.join(parent_dir, pdf_file)
            if not os.path.exists(source_path):
                logger.warning(f"PDF file not found: {source_path}, skipping")
                continue
            
            # Prepare page texts in the format expected by the chunker
            page_texts = []
            for page_num, page_data in pdf_info.get("page_data", {}).items():
                try:
                    page_num = int(page_num)
                    page_text = page_data.get("text", "")
                    
                    if not page_text.strip():
                        continue
                    
                    # Build minimal metadata
                    metadata = {
                        "source": pdf_file,
                        "page": page_num,
                        "total_pages": pdf_info.get("total_pages", 0),
                        "image_url": page_data.get("image_url")
                    }
                    
                    # Add headings if available
                    if "headings" in page_data:
                        for level, heading in page_data["headings"].items():
                            metadata[f"h{level}"] = heading
                    
                    page_texts.append({
                        "text": page_text,
                        "page": page_num,
                        "metadata": metadata
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing page {page_num} of {pdf_file}: {e}")
                    continue
            
            # Generate chunks for haystack
            chunks = haystack_store.chunk_document_with_cross_page_context(page_texts)
            
            if not chunks:
                logger.warning(f"No chunks generated for {pdf_file}")
                continue
                
            logger.info(f"Generated {len(chunks)} chunks for {pdf_file}")
            
            # Add chunks to haystack store
            points_added = haystack_store.add_points(chunks)
            total_chunks += points_added
            
            logger.info(f"Added {points_added} chunks to haystack store for {pdf_file}")
            
        except Exception as e:
            logger.error(f"Error processing {pdf_file} for haystack: {e}", exc_info=True)
    
    logger.info(f"Finished loading documents. Added {total_chunks} chunks to haystack store")

if __name__ == "__main__":
    main() 