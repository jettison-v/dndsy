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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_processing.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class DataProcessor:
    def __init__(self):
        """Initialize the data processor."""
        self.vector_store = QdrantStore()
        self.processed_sources = set()
    
    def process_pdfs(self, pdf_dir: str) -> List[Dict[str, Any]]:
        """Process PDF files and return documents."""
        pdf_dir = Path(pdf_dir)
        documents = []
        
        # Find all PDF files
        pdf_files = []
        for root, _, files in os.walk(pdf_dir):
            for file in sorted(files):
                if file.lower().endswith('.pdf'):
                    pdf_files.append(Path(root) / file)
        
        logging.info(f"Found {len(pdf_files)} PDF files to process")
        
        for pdf_path in tqdm(pdf_files, desc="Processing PDFs"):
            try:
                # Check if already processed
                rel_path = str(pdf_path.relative_to(pdf_dir))
                if rel_path in self.processed_sources:
                    logging.info(f"Skipping already processed PDF: {pdf_path}")
                    continue
                
                # Extract text
                doc = fitz.open(pdf_path)
                text = ""
                for page in doc:
                    text += page.get_text() + "\n\n"
                doc.close()
                
                # Create document
                document = {
                    "text": text,
                    "metadata": {
                        "source": rel_path,
                        "type": "pdf",
                        "folder": str(pdf_path.parent),
                        "filename": pdf_path.name,
                        "processed_at": datetime.now().isoformat()
                    }
                }
                documents.append(document)
                self.processed_sources.add(rel_path)
                
            except Exception as e:
                logging.error(f"Error processing {pdf_path}: {str(e)}")
        
        return documents
    
    def process_web_content(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Process web content and return documents."""
        documents = []
        
        for url in tqdm(urls, desc="Processing web content"):
            try:
                # Check if already processed
                if url in self.processed_sources:
                    logging.info(f"Skipping already processed URL: {url}")
                    continue
                
                # Fetch content
                response = requests.get(url)
                response.raise_for_status()
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract text (customize based on the website structure)
                text = soup.get_text()
                
                # Create document
                document = {
                    "text": text,
                    "metadata": {
                        "source": url,
                        "type": "web",
                        "processed_at": datetime.now().isoformat()
                    }
                }
                documents.append(document)
                self.processed_sources.add(url)
                
            except Exception as e:
                logging.error(f"Error processing {url}: {str(e)}")
        
        return documents
    
    def process_api_data(self, api_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process API data and return documents."""
        documents = []
        
        for item in tqdm(api_data, desc="Processing API data"):
            try:
                # Check if already processed
                item_id = item.get("id")
                if item_id in self.processed_sources:
                    logging.info(f"Skipping already processed API item: {item_id}")
                    continue
                
                # Convert API data to text (customize based on the API response structure)
                text = json.dumps(item, indent=2)
                
                # Create document
                document = {
                    "text": text,
                    "metadata": {
                        "source": f"api_{item_id}",
                        "type": "api",
                        "processed_at": datetime.now().isoformat()
                    }
                }
                documents.append(document)
                self.processed_sources.add(item_id)
                
            except Exception as e:
                logging.error(f"Error processing API item: {str(e)}")
        
        return documents
    
    def process_all_sources(self):
        """Process all data sources and add to vector store."""
        # Process PDFs
        pdf_documents = self.process_pdfs("data/pdfs")
        if pdf_documents:
            logging.info(f"Adding {len(pdf_documents)} PDF documents to vector store")
            self.vector_store.add_documents(pdf_documents)
        
        # Process web content (example URLs)
        web_urls = [
            # Add your forum URLs here
        ]
        web_documents = self.process_web_content(web_urls)
        if web_documents:
            logging.info(f"Adding {len(web_documents)} web documents to vector store")
            self.vector_store.add_documents(web_documents)
        
        # Process API data (example data)
        api_data = [
            # Add your API data here
        ]
        api_documents = self.process_api_data(api_data)
        if api_documents:
            logging.info(f"Adding {len(api_documents)} API documents to vector store")
            self.vector_store.add_documents(api_documents)
        
        # Save the vector store state
        self.vector_store.save("data/qdrant_index", "data/documents.json")
        logging.info("Processing complete!")

def main():
    processor = DataProcessor()
    processor.process_all_sources()

if __name__ == "__main__":
    main() 