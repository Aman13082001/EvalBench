FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY pyproject.toml ./
COPY evalbench/ ./evalbench/

# Install Python deps
RUN pip install --no-cache-dir -e .

# Run as an unprivileged user
RUN useradd -m -u 1000 evalbench && chown -R evalbench:evalbench /app
USER evalbench

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "evalbench.api.main:app", "--host", "0.0.0.0", "--port", "8000"]