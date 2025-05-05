FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including curl
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust for tiktoken
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy requirements first to leverage Docker cache
COPY ../requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY .. .

# Create necessary directories
RUN mkdir -p /app/data/processed

# Expose the port provided by the environment or default to 5001
EXPOSE ${PORT:-5001}

# Health check (Still points to localhost:5001 for now, might need adjustment)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Start the Gunicorn server, binding to the dynamic PORT or defaulting to 5001
# Use shell form to allow $PORT expansion
CMD gunicorn --bind "0.0.0.0:${PORT:-5001}" --worker-class gevent --workers 1 --timeout 120 app:app

# The entrypoint is now handled by docker-compose.yml 