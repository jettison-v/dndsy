# D&D Knowledge Base

A web application that provides a searchable knowledge base for Dungeons & Dragons content using vector embeddings and semantic search.

## Project Structure

### Core Files
- `app.py` - Main Flask application with routes and web interface
- `main.py` - Entry point for running the application
- `llm.py` - LLM integration for processing and generating responses
- `process_data_sources.py` - Script for processing various data sources (PDFs, web content) into the vector store

### Vector Store
- `vector_store/qdrant_store.py` - Implementation of Qdrant vector store for semantic search

### Web Interface
- `templates/`
  - `index.html` - Main search interface
  - `login.html` - User authentication page
- `static/`
  - `css/` - Stylesheets
  - `js/` - JavaScript files
  - `img/` - Images and icons

### Deployment
- `Dockerfile` - Container configuration for the application
- `docker-compose.yml` - Docker Compose configuration for running Qdrant and the application
- `Procfile` - Process file for Heroku deployment
- `runtime.txt` - Python runtime specification
- `heroku.json` - Heroku configuration
- `.env` - Environment variables (not tracked in git)

### Data
- `data/` - Directory for storing PDFs and processed data

## Setup and Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Start Qdrant vector store:
```bash
docker-compose up -d qdrant
```

3. Process data sources:
```bash
python process_data_sources.py
```

4. Run the application:
```bash
python main.py
```

## Features

- Semantic search across D&D content
- PDF document processing
- Web content integration
- Vector-based similarity search
- User authentication
- Modern web interface

## Technologies Used

- Python 3.13
- Flask
- Qdrant Vector Store
- Sentence Transformers
- Docker
- HTML/CSS/JavaScript

## Development

To contribute to the project:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Add your license information here] 