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
    # The base image ships a pip and setuptools with known advisories;
    # the audit that runs in CI would flag the image as shipped.
    && pip install --no-cache-dir --upgrade pip setuptools \
    # torch first, from the index that serves it without the NVIDIA
    # CUDA libraries. pip's default wheel carries them: about eight
    # gigabytes of GPU driver for a container that has no GPU, calls
    # hosted providers over HTTP, and runs one 90 MB embedding model
    # on the CPU. Installed before the package, so the dependency is
    # already satisfied when sentence-transformers asks for it.
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -e . \
    && rm -rf evalbench

# Now bring in the real README and source (fast layers). suites/ ships
# too: the bundled benchmarks the workspace offers are read from it.
COPY README.md ./
COPY evalbench/ ./evalbench/
COPY suites/ ./suites/

# Bake the embedding model into the image. Without this the first
# semantic check on a cold instance downloads 90 MB from the Hugging
# Face hub before it can score anything — slow on a free tier that
# sleeps, and a failure mode when the hub is unreachable or rate
# limits. HF_HOME lives under /app so the unprivileged user below
# inherits it with the chown.
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Run as an unprivileged user
RUN useradd -m -u 1000 evalbench && chown -R evalbench:evalbench /app
USER evalbench

# The port is the platform's to choose. Compose publishes 8000, Hugging
# Face Spaces serves 7860, Render and Railway inject $PORT and expect the
# process to read it. One image, told which — rather than a second
# Dockerfile per host, which is the copy that goes stale.
EXPOSE 8000
ENV PORT=8000

# Shell form, so $PORT is expanded by the shell at start rather than
# passed to uvicorn as the literal string.
CMD uvicorn evalbench.api.main:app --host 0.0.0.0 --port ${PORT:-8000}