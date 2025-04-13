"""
Search Helper Module
-------------------
Provides a standardized interface for vector store search operations.
This abstraction reduces code duplication across different vector store
implementations while allowing specialized functionality where needed.

The SearchHelper base class defines common patterns for:
- Vector similarity search
- Filter-based document retrieval
- Error handling and logging
- Result formatting

Each vector store implementation extends this base class and provides
its specific implementation of the abstract methods.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

class SearchHelper(ABC):
    """Base class for standardizing search operations across vector stores."""
    
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        
    @abstractmethod
    def _execute_vector_search(self, query_vector: List[float], limit: int) -> List[Dict[str, Any]]:
        """Execute raw vector search against the store. To be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _execute_filter_search(self, filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Execute filter-based search. To be implemented by subclasses."""
        pass
        
    @abstractmethod
    def _get_document_by_filter(self, filter_conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get a single document by filter. To be implemented by subclasses."""
        pass
    
    @abstractmethod
    def _get_all_documents_raw(self, limit: int) -> List[Dict[str, Any]]:
        """Get all documents from store. To be implemented by subclasses."""
        pass
    
    def search(self, query_vector: List[float], query: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Standard search implementation with common error handling."""
        try:
            logging.info(f"Searching {self.collection_name} for: '{query if query else 'vector-only'}'")
            
            if not query_vector:
                logging.warning("Search called with empty query vector")
                return []
                
            results = self._execute_vector_search(query_vector, limit)
            logging.info(f"Search returned {len(results)} results")
            return results
            
        except Exception as e:
            logging.error(f"Error during search: {e}", exc_info=True)
            return []
    
    def get_details_by_source_page(self, source: str, page: int) -> Optional[Dict[str, Any]]:
        """Get details for a specific source and page with standard error handling."""
        try:
            logging.info(f"Retrieving details for {source} page {page}")
            
            filter_conditions = self._create_source_page_filter(source, page)
            result = self._get_document_by_filter(filter_conditions)
            
            if not result:
                logging.warning(f"No documents found for {source} page {page}")
                return None
                
            return result
            
        except Exception as e:
            logging.error(f"Error retrieving page details: {e}", exc_info=True)
            return None
    
    def get_all_documents(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get all documents with common error handling."""
        try:
            logging.info(f"Retrieving all documents (limit: {limit})")
            
            documents = self._get_all_documents_raw(limit)
            logging.info(f"Retrieved {len(documents)} documents")
            return documents
            
        except Exception as e:
            logging.error(f"Error retrieving all documents: {e}", exc_info=True)
            return []
    
    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Default implementation for creating a source/page filter.
        Can be overridden by subclasses to customize filter structure."""
        return {
            "source": source,
            "page": page
        }
    
    def format_search_result(self, result_doc: Any) -> Dict[str, Any]:
        """Standard formatting for search results."""
        # Default implementation - subclasses will override with store-specific logic
        return {
            "text": getattr(result_doc, "text", ""),
            "metadata": getattr(result_doc, "metadata", {}),
            "score": getattr(result_doc, "score", 0.0)
        } 