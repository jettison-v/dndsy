import os
from openai import OpenAI
from vector_store.qdrant_store import QdrantStore
import logging
import tiktoken

# Set up logging
logging.basicConfig(level=logging.INFO)

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

def get_relevant_context(query: str, limit: int = 3) -> str:
    """Search the vector store for relevant context."""
    try:
        results = vector_store.search(query, limit=limit)
        if not results:
            return ""
        
        # Format the context with source information
        context_parts = []
        total_tokens = 0
        max_tokens_per_result = 800  # Reserve some tokens for the system message and query
        
        for result in results:
            source = result['metadata']['source'].split('/')[-1].replace('.pdf', '')
            text = result['text'].strip()
            
            # Create the context piece
            context_piece = f"From {source}:\n{text}"
            
            # Check token count
            tokens = num_tokens_from_string(context_piece)
            if tokens > max_tokens_per_result:
                context_piece = truncate_text(context_piece, max_tokens_per_result)
                tokens = num_tokens_from_string(context_piece)
            
            # Add if we're still under the total limit
            if total_tokens + tokens <= 2400:  # Keep total context under 3000 tokens
                context_parts.append(context_piece)
                total_tokens += tokens
            else:
                break
        
        return "\n\n".join(context_parts)
    except Exception as e:
        logging.error(f"Error searching vector store: {str(e)}")
        return ""

def ask_dndsy(prompt: str) -> str:
    """
    Process a query using both vector store and OpenAI.
    First searches for relevant context in the vector store,
    then uses that context to inform the OpenAI response.
    """
    try:
        # Get relevant context from vector store
        context = get_relevant_context(prompt)
        logging.info(f"Found context: {bool(context)}")
        
        # Prepare the system message
        system_message = (
            "You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. "
            "You may reference 2014 (5e) rules only for comparisons, and you must clearly say so. "
            "Never answer using 2014 rules alone. Be concise and helpful.\n\n"
        )
        
        # If we have context, add it to the system message
        if context:
            system_message += (
                "Use the following information from the official 2024 D&D materials to inform your response. "
                "If the provided context fully answers the question, use it. "
                "If the context is only partially relevant, combine it with your general knowledge:\n\n"
                f"{context}\n\n"
            )
        else:
            system_message += (
                "No specific rule reference was found in the 2024 materials for this query. "
                "Provide a general response based on your knowledge of D&D 2024 rules.\n\n"
            )
        
        # Make the API call
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Using 3.5 for testing, can switch to 4 later
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=500
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        error_msg = f"Error processing query: {str(e)}"
        logging.error(error_msg)
        return error_msg