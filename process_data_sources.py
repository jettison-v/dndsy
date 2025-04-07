import os
import json
from pathlib import Path
import fitz  # PyMuPDF
from vector_store.qdrant_store import QdrantStore
from tqdm import tqdm
import logging
import sys
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re # Import re for path cleaning

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_processing.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Define base directory for images relative to static folder
PDF_IMAGE_DIR = "pdf_page_images"
STATIC_DIR = "static" # Define static directory name

class DataProcessor:
    def __init__(self):
        """Initialize the data processor."""
        self.vector_store = QdrantStore()
        self.processed_sources = set()
    
    def _clean_filename(self, filename: str) -> str:
        """Remove potentially problematic characters for filenames/paths."""
        # Remove directory separators and replace other non-alphanumeric with underscore
        cleaned = re.sub(r'[/\\]+', '_', filename) # Replace slashes with underscore
        cleaned = re.sub(r'[^a-zA-Z0-9_\-\.]+', '_', cleaned) # Replace others
        return cleaned

    def process_pdfs(self, pdf_dir: str) -> List[Dict[str, Any]]:
        """Process PDF files, generate page images, and return documents."""
        pdf_dir_path = Path(pdf_dir)
        documents = []
        
        # Create base image directory if it doesn't exist
        base_image_output_dir = Path(STATIC_DIR) / PDF_IMAGE_DIR
        base_image_output_dir.mkdir(parents=True, exist_ok=True)

        # Find all PDF files
        pdf_files = list(pdf_dir_path.rglob('*.pdf'))
        logging.info(f"Found {len(pdf_files)} PDF files to process")
        
        for pdf_path in tqdm(pdf_files, desc="Processing PDFs"):
            try:
                rel_path = str(pdf_path.relative_to(pdf_dir_path))
                # Clean the relative path to use as a directory name
                pdf_image_sub_dir_name = self._clean_filename(rel_path.replace('.pdf', ''))
                pdf_image_output_dir = base_image_output_dir / pdf_image_sub_dir_name
                pdf_image_output_dir.mkdir(parents=True, exist_ok=True)

                # Extract text and generate images page by page
                doc = fitz.open(pdf_path)
                total_pages = len(doc) # Get total page count

                for page_num, page in enumerate(doc): 
                    page_text = page.get_text().strip()
                    if not page_text: 
                        continue

                    page_label = page_num + 1 
                    page_source_id = f"{rel_path}_page_{page_label}"

                    if page_source_id in self.processed_sources:
                        # logging.info(f"Skipping already processed page: {page_source_id}") # Can be verbose
                        continue
                    
                    # Generate image
                    image_filename = f"page_{page_label}.png"
                    image_save_path = pdf_image_output_dir / image_filename
                    image_url_path = f'/{STATIC_DIR}/{PDF_IMAGE_DIR}/{pdf_image_sub_dir_name}/{image_filename}'
                    
                    try:
                        pix = page.get_pixmap(dpi=150) # Render at 150 DPI
                        pix.save(str(image_save_path))
                    except Exception as img_e:
                        logging.error(f"Error generating image for {rel_path} page {page_label}: {img_e}")
                        image_url_path = None # Set path to None if image fails

                    # Create document per page
                    document = {
                        "text": page_text, 
                        "metadata": {
                            "source": rel_path, 
                            "page": page_label, 
                            "image_url": image_url_path,
                            "total_pages": total_pages, # Add total pages
                            "source_dir": pdf_image_sub_dir_name, # Add cleaned source dir name
                            "type": "pdf",
                            "folder": str(pdf_path.parent.relative_to(pdf_dir_path)), # Store relative folder
                            "filename": pdf_path.name,
                            "processed_at": datetime.now().isoformat()
                        }
                    }
                    documents.append(document)
                    self.processed_sources.add(page_source_id) 

                doc.close()

            except Exception as e:
                logging.error(f"Error processing {pdf_path}: {str(e)}")
        
        return documents
    
    def process_all_sources(self):
        """Process all data sources and add to vector store."""
        # Process PDFs
        pdf_documents = self.process_pdfs("data/pdfs")
        if pdf_documents:
            logging.info(f"Adding {len(pdf_documents)} PDF documents to vector store")
            self.vector_store.add_documents(pdf_documents)
        
        logging.info("PDF Processing complete!") # Updated log message

def main():
    processor = DataProcessor()
    processor.process_all_sources()

if __name__ == "__main__":
    main() 