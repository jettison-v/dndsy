import os
from openai import OpenAI
from vector_store.qdrant_store import QdrantStore
import logging
import tiktoken

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is not set")
client = OpenAI()

# Initialize vector store
vector_store = QdrantStore()

def num_tokens_from_string(string: str, model: str = "gpt-3.5-turbo") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def truncate_text(text: str, max_tokens: int = 1000, model: str = "gpt-3.5-turbo") -> str:
    """Truncate text to fit within token limit."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoding.decode(tokens[:max_tokens]) + "..."

def get_relevant_context(query: str, limit: int = 5) -> list[dict]:
    """Search the vector store for relevant context."""
    try:
        # Log the search query
        logger.info(f"Searching for context with query: {query}")
        
        # Increase limit to get more potential matches
        results = vector_store.search(query, limit=limit)
        logger.info(f"Found {len(results)} results from vector store")
        
        if not results:
            logger.warning("No results found in vector store")
            return []
        
        # Format the context with source information
        context_parts = []
        total_tokens = 0
        max_tokens_per_result = 1000  # Increased token limit per result
        
        for idx, result in enumerate(results):
            metadata = result['metadata'] # Get metadata dict
            source = metadata['source'].split('/')[-1].replace('.pdf', '')
            text = result['text'].strip()
            score = result.get('score', 0)  # Get similarity score if available
            page = metadata.get('page', 'unknown')
            image_url = metadata.get('image_url', None)
            total_pages = metadata.get('total_pages', None) # Get total pages
            source_dir = metadata.get('source_dir', None) # Get source dir
            
            logger.info(f"Result {idx + 1} from {source} with score {score}")
            
            # Create the context piece with detailed source information
            context_piece = {
                'text': text, # Keep text for potential future use (e.g., alt text)
                'source': source,
                'page': page,
                'image_url': image_url,
                'total_pages': total_pages,
                'source_dir': source_dir,
                'score': score
            }
            
            # Check token count
            tokens = num_tokens_from_string(text)
            if tokens > max_tokens_per_result:
                context_piece['text'] = truncate_text(text, max_tokens_per_result)
                tokens = num_tokens_from_string(context_piece['text'])
            
            # Add if we're still under the total limit
            if total_tokens + tokens <= 3000:  # Increased total token limit
                context_parts.append(context_piece)
                total_tokens += tokens
                logger.info(f"Added context from {source} (page {page}) ({tokens} tokens)")
            else:
                logger.info(f"Skipping remaining results due to token limit")
                break
        
        return context_parts
    except Exception as e:
        logger.error(f"Error searching vector store: {str(e)}")
        return []

def ask_dndsy(prompt: str) -> dict:
    """
    Process a query using both vector store and OpenAI.
    First searches for relevant context in the vector store,
    then uses that context to inform the OpenAI response.
    Returns a dictionary containing the response and source information.
    """
    try:
        # Get relevant context from vector store
        context_parts = get_relevant_context(prompt)
        logger.info(f"Context found: {bool(context_parts)}")
        
        # Track sources
        sources = []
        context_text = ""
        if context_parts:
            # Format context for the LLM
            for part in context_parts:
                source = f"{part['source']} (page {part['page']})"
                if source not in sources:
                    sources.append(source)
                context_text += f"From {source}:\n{part['text']}\n\n"
            logger.info(f"Found sources: {sources}")
        
        # Prepare the system message
        system_message = (
            "You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. "
            "Follow these guidelines:\n"
            "1. ALWAYS prioritize using the provided 2024 rules context when available\n"
            "2. Only fall back to general knowledge if NO relevant context is found\n"
            "3. If comparing with 5e (2014) rules, clearly state this\n"
            "4. Be specific and cite rules when possible\n"
            "5. Keep responses clear and concise\n\n"
        )
        
        # If we have context, add it to the system message
        if context_text:
            system_message += (
                "Use the following official 2024 D&D rules to answer the question. "
                "This information comes directly from the source material, so prioritize using it:\n\n"
                f"{context_text}\n\n"
            )
        else:
            system_message += (
                "WARNING: No specific rule reference was found in the 2024 materials for this query. "
                "Provide a general response based on your knowledge of D&D 2024 rules, "
                "but note that this response is not from the official documentation.\n\n"
            )
        
        # Make the API call
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Using 3.5 for testing, can switch to 4 later
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Reduced temperature for more focused responses
            max_tokens=500
        )
        
        # Prepare the response with source information
        result = {
            "response": response.choices[0].message.content,
            "sources": sources if sources else ["GPT-3.5-turbo"],
            "using_context": bool(context_parts),
            "context_parts": context_parts if context_parts else []
        }
        
        return result
        
    except Exception as e:
        error_msg = f"Error processing query: {str(e)}"
        logger.error(error_msg)
        return {"response": error_msg, "sources": [], "using_context": False, "context_parts": []}