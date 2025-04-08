import os
from pathlib import Path
import sys

def setup_environment():
    """Set up the environment variables for the project."""
    env_file = Path('.env')
    
    # Check if .env already exists
    if env_file.exists():
        print("\nFound existing .env file.")
        update = input("Would you like to update it? (y/n): ").lower()
        if update != 'y':
            print("Keeping existing .env file.")
            return
    
    # Get OpenAI API key
    api_key = input("\nPlease enter your OpenAI API key: ").strip()
    if not api_key:
        print("Error: OpenAI API key is required.")
        sys.exit(1)
    
    # Write to .env file
    with open(env_file, 'w') as f:
        f.write(f"OPENAI_API_KEY={api_key}\n")
        f.write("QDRANT_HOST=localhost\n")
        f.write("QDRANT_PORT=6333\n")
    
    print("\nEnvironment variables have been set up!")
    print("Please restart your terminal or run 'source .env' to apply the changes.")

if __name__ == "__main__":
    setup_environment() 