FROM python:3.11-slim

WORKDIR /app

# Install deps against a stub package so the heavy layer is cached
# until pyproject.toml changes (streamlit needs the backend deps too).
COPY pyproject.toml README.md ./
RUN mkdir evalbench \
    && printf '' > evalbench/__init__.py \
    && pip install --no-cache-dir -e . \
    && rm -rf evalbench

# Real source (fast layers).
COPY evalbench/ ./evalbench/
COPY frontend/app.py ./frontend/

# Run as an unprivileged user
RUN useradd -m -u 1000 evalbench && chown -R evalbench:evalbench /app
USER evalbench

EXPOSE 8501

CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]