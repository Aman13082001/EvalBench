FROM python:3.11-slim

WORKDIR /app

# Copy backend deps (streamlit needs them too)

COPY pyproject.toml ./
COPY evalbench/ ./evalbench/
RUN pip install --no-cache-dir -e .

# Copy frontend code

COPY frontend/app.py ./frontend/

EXPOSE 8501

CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]