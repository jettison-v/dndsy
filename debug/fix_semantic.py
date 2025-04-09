"""
Fix Semantic Collection Script

This script creates the semantic collection and populates it with documents
from the S3 PDFs.
"""
import os
import sys
import logging
from pathlib import Path
import datetime
import argparse
from dotenv import load_dotenv

# Add parent directory to path to make imports work properly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from vector_store import get_vector_store
from vector_store.qdrant_store import QdrantClient
from scripts.process_data_sources import DataProcessor, s3_client, AWS_S3_BUCKET_NAME, AWS_S3_PDF_PREFIX
from scripts.process_data_sources import PROCESS_HISTORY_FILE

# Ensure logs directory exists
logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'fix_semantic.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
env_path = Path(os.path.dirname(os.path.dirname(__file__))) / '.env'
load_dotenv(dotenv_path=env_path)

def fix_semantic_collection(reset_history=False):
    logger.info("Starting semantic collection fix script")
    
    # Reset processing history if requested
    if reset_history:
        logger.info("Resetting processing history as requested")
        try:
            if os.path.exists(PROCESS_HISTORY_FILE):
                os.remove(PROCESS_HISTORY_FILE)
                logger.info(f"Deleted {PROCESS_HISTORY_FILE}")
            else:
                logger.info(f"No existing {PROCESS_HISTORY_FILE} to delete")
        except Exception as e:
            logger.error(f"Error deleting process history: {e}")
    
    # Initialize Qdrant client
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    # Determine if it's a cloud URL
    is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")

    if is_cloud:
        logger.info(f"Connecting to Qdrant Cloud at: {qdrant_host}")
        client = QdrantClient(
            url=qdrant_host, 
            api_key=qdrant_api_key,
            timeout=60
        )
    else:
        logger.info(f"Connecting to local Qdrant at: {qdrant_host}")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=port, timeout=60)
    
    # Check if collections exist
    collections = client.get_collections().collections
    collection_names = [col.name for col in collections]
    
    logger.info(f"Existing collections: {collection_names}")
    
    # Delete semantic collection if it exists
    if "dnd_semantic" in collection_names:
        logger.info("Deleting existing semantic collection")
        client.delete_collection("dnd_semantic")
    
    # Update the SemanticStore class to handle BM25 errors
    from vector_store.semantic_store import SemanticStore
    
    # Monkey patch the add_documents method to handle BM25 errors
    original_add_documents = SemanticStore.add_documents
    
    def patched_add_documents(self, documents):
        """Patched version of add_documents that handles BM25 errors"""
        # Import necessary modules
        from qdrant_client.http import models
        from langchain.schema import Document
        
        if not documents:
            return
        
        # Reset BM25 documents and retriever since we're adding new content
        self.bm25_documents = []
        
        # Prepare points for batch insertion
        points = []
        doc_id_counter = 0
        total_chunks = 0
        embedding_count = 0
        start_time = datetime.datetime.now()
        
        logging.info(f"[{start_time.strftime('%H:%M:%S')}] Starting semantic processing of {len(documents)} documents")
        
        for doc in documents:
            original_text = doc["text"]
            metadata = doc["metadata"].copy()
            
            # Use LangChain's recursive text splitter for better chunking
            # This creates semantically meaningful chunks with context preservation
            chunks = self.text_splitter.split_text(original_text)
            total_chunks += len(chunks)
            
            for i, chunk_text in enumerate(chunks):
                # Skip empty chunks
                if not chunk_text.strip():
                    continue
                
                # Update metadata with chunk info
                chunk_metadata = metadata.copy()
                chunk_metadata["chunk_index"] = i
                chunk_metadata["chunk_count"] = len(chunks)
                
                # Generate embedding
                embedding = self._get_embedding(chunk_text)
                embedding_count += 1
                
                if embedding_count % 50 == 0:
                    elapsed = (datetime.datetime.now() - start_time).total_seconds()
                    logging.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Processed {embedding_count}/{total_chunks} embeddings ({(embedding_count/total_chunks*100):.1f}%) - {elapsed:.1f} seconds elapsed")
                
                # Create point for Qdrant
                point = models.PointStruct(
                    id=doc_id_counter,
                    vector=embedding,
                    payload={
                        "text": chunk_text,
                        "metadata": chunk_metadata
                    }
                )
                points.append(point)
                
                # Also add to BM25 documents for hybrid search
                self.bm25_documents.append(
                    Document(
                        page_content=chunk_text,
                        metadata=chunk_metadata
                    )
                )
                
                doc_id_counter += 1
        
        # Initialize BM25 retriever with the documents
        if self.bm25_documents:
            logging.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Initializing BM25 retriever with {len(self.bm25_documents)} documents")
            try:
                from langchain_community.retrievers import BM25Retriever
                self.bm25_retriever = BM25Retriever.from_documents(
                    self.bm25_documents
                )
                logging.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] BM25 retriever initialization complete")
            except ImportError as e:
                logging.warning(f"Could not initialize BM25 retriever: {e}. Continuing without BM25.")
                self.bm25_retriever = None
        
        # Insert points in batches
        batch_size = 100
        batch_count = (len(points) + batch_size - 1) // batch_size  # Ceiling division
        
        logging.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Uploading {len(points)} embeddings to Qdrant in {batch_count} batches")
        
        for i in range(0, len(points), batch_size):
            batch_num = i // batch_size + 1
            batch = points[i:i + batch_size]
            batch_start = datetime.datetime.now()
            
            logging.info(f"[{batch_start.strftime('%H:%M:%S')}] Uploading batch {batch_num}/{batch_count} ({len(batch)} points)")
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch
            )
            
            batch_end = datetime.datetime.now()
            batch_duration = (batch_end - batch_start).total_seconds()
            logging.info(f"[{batch_end.strftime('%H:%M:%S')}] Batch {batch_num}/{batch_count} complete in {batch_duration:.1f} seconds")
        
        end_time = datetime.datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        logging.info(f"[{end_time.strftime('%H:%M:%S')}] Semantic processing complete - {total_duration:.1f} seconds total")
        logging.info(f"Added {len(points)} semantic chunks from {len(documents)} original documents")
    
    # Apply the monkey patch
    SemanticStore.add_documents = patched_add_documents
    
    # Get the semantic store
    semantic_store = get_vector_store("semantic")
    logger.info("Created semantic store")
    
    # Initialize DataProcessor
    logger.info("Initializing DataProcessor to process PDFs")
    processor = DataProcessor()
    
    # Create a custom method that only processes documents for the semantic store
    # This modified version skips image generation
    def process_pdfs_for_semantic():
        logger.info("Processing PDFs from S3 for semantic store only...")
        
        # Check if S3 client is available
        if s3_client is None:
            logger.error("S3 client is not initialized. AWS credentials may be missing.")
            return False
            
        # Ensure prefix ends with a slash if it's not empty
        s3_prefix = AWS_S3_PDF_PREFIX
        if s3_prefix and not s3_prefix.endswith('/'):
            s3_prefix += '/'
        
        try:
            # List all PDFs in the S3 bucket
            logger.info(f"Listing PDFs in S3 bucket: {AWS_S3_BUCKET_NAME} with prefix: {s3_prefix}")
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=s3_prefix)
            
            pdf_files_s3_keys = []
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        # Only include PDF files
                        if key.lower().endswith('.pdf'):
                            pdf_files_s3_keys.append(key)
            
            logger.info(f"Found {len(pdf_files_s3_keys)} PDFs in S3")
            
            # Process each PDF
            for i, s3_pdf_key in enumerate(pdf_files_s3_keys):
                logger.info(f"Processing PDF {i+1}/{len(pdf_files_s3_keys)}: {s3_pdf_key}")
                
                try:
                    # Download PDF content from S3
                    pdf_object = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                    pdf_bytes = pdf_object['Body'].read()
                    
                    # Extract PDF information
                    import fitz  # PyMuPDF
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    total_pages = len(doc)
                    logger.info(f"PDF has {total_pages} pages")
                    
                    # Extract text from each page
                    semantic_docs = []
                    rel_path = s3_pdf_key[len(s3_prefix):] if s3_pdf_key.startswith(s3_prefix) else s3_pdf_key
                    pdf_filename = rel_path.split('/')[-1]
                    
                    for page_num, page in enumerate(doc):
                        if page_num % 20 == 0 and page_num > 0:
                            logger.info(f"  Processed {page_num}/{total_pages} pages")
                        
                        page_text = page.get_text().strip()
                        if not page_text:
                            continue
                        
                        page_label = page_num + 1
                        
                        # Create document metadata (minimal version without image URLs)
                        metadata = {
                            "source": s3_pdf_key,
                            "filename": pdf_filename,
                            "page": page_label,
                            "total_pages": total_pages,
                            "type": "pdf",
                            "folder": str(Path(rel_path).parent),
                            "processed_at": datetime.datetime.now().isoformat()
                        }
                        
                        # Add to semantic documents list
                        semantic_docs.append({
                            "text": page_text,
                            "metadata": metadata
                        })
                    
                    # Add documents to semantic store
                    if semantic_docs:
                        logger.info(f"Adding {len(semantic_docs)} documents to semantic store")
                        semantic_store.add_documents(semantic_docs)
                    
                    # Close the document
                    doc.close()
                    
                except Exception as e:
                    logger.error(f"Error processing PDF {s3_pdf_key}: {e}")
                    continue
            
            return True
            
        except Exception as e:
            logger.error(f"Error listing PDFs in S3: {e}")
            return False
    
    # Process PDFs for semantic collection
    start_time = datetime.datetime.now()
    logger.info(f"Starting semantic processing at {start_time}")
    
    success = process_pdfs_for_semantic()
    
    end_time = datetime.datetime.now()
    total_duration = (end_time - start_time).total_seconds()
    logger.info(f"Semantic processing completed in {total_duration:.1f} seconds")
    
    # Verify the semantic collection has been populated
    try:
        semantic_count = client.count("dnd_semantic").count
        logger.info(f"Semantic collection now contains {semantic_count} documents")
        return success
    except Exception as e:
        logger.error(f"Error verifying semantic collection: {e}")
        return False

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Fix the semantic collection by reprocessing PDFs")
    parser.add_argument('--reset-history', action='store_true', 
                        help="Reset processing history (forces complete reprocessing)")
    args = parser.parse_args()
    
    success = fix_semantic_collection(reset_history=args.reset_history)
    if success:
        logger.info("Semantic collection fix completed successfully")
    else:
        logger.error("Semantic collection fix failed") 