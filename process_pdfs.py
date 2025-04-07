import os
from pathlib import Path
from process_data_sources import DataProcessor
import logging
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pdf_processing.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

def process_pdfs():
    """Process PDF files from data/pdfs directory and its subfolders and add them to the vector store."""
    pdf_dir = Path("data/pdfs")
    
    if not pdf_dir.exists():
        logging.error("data/pdfs directory does not exist")
        return False
    
    # Process the PDFs
    processor = DataProcessor()
    documents = processor.process_pdfs("data/pdfs")
    
    if documents:
        logging.info(f"Successfully processed {len(documents)} PDF documents")
        return True
    else:
        logging.warning("No documents were processed")
        return False

if __name__ == "__main__":
    success = process_pdfs()
    
    if success:
        print("\nPDF processing completed successfully!")
        print("You can now use the vector store to search through the content.")
    else:
        print("\nPDF processing completed with warnings or errors.")
        print("Check pdf_processing.log for details.") 