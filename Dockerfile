FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps against a stub package first so this layer (which
# pulls torch/sentence-transformers) is cached until pyproject.toml
# actually changes — editing source no longer triggers a reinstall.
#
# The README is stubbed rather than copied: pyproject declares it as the
# long description, so copying the real one would put every doc edit in
# this layer's cache key and re-download torch to publish a typo fix.
COPY pyproject.toml ./
RUN mkdir evalbench \
    && printf '' > evalbench/__init__.py \
    && printf '' > README.md \
    && pip install --no-cache-dir -e . \
    && rm -rf evalbench

# Now bring in the real README and source (fast layers).
COPY README.md ./
COPY evalbench/ ./evalbench/

# Run as an unprivileged user
RUN useradd -m -u 1000 evalbench && chown -R evalbench:evalbench /app
USER evalbench

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "evalbench.api.main:app", "--host", "0.0.0.0", "--port", "8000"]