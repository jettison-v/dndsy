import os
import sys
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# Add the project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

# Import our vector store
from vector_store import get_vector_store

def main():
    """Test the get_details_by_source_page method directly."""
    try:
        # Get the haystack store
        vector_store = get_vector_store("haystack")
        print("Successfully initialized haystack store.")
        
        # Get details for a specific page
        source = "source-pdfs/2024 Players Handbook.pdf"
        page = 172
        
        print(f"Trying to get details for {source}, page {page}...")
        details = vector_store.get_details_by_source_page(source, page)
        
        if details:
            print("Success! Found details:")
            print(f"  Text: {details.get('text')[:100]}...")
            print(f"  Image URL: {details.get('image_url')}")
            print(f"  Metadata: {details.get('metadata')}")
        else:
            print(f"No details found for {source}, page {page}")
            
        # Try a different store type
        print("\nTrying standard store...")
        std_store = get_vector_store("standard")
        std_details = std_store.get_details_by_source_page(source, page)
        
        if std_details:
            print("Success with standard store!")
            print(f"  Image URL: {std_details.get('image_url')}")
        else:
            print("No details found with standard store")
            
    except Exception as e:
        logger.exception(f"Error in test: {e}")

if __name__ == "__main__":
    main() 