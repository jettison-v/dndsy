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

# Expose the port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# The entrypoint is now handled by docker-compose.yml 