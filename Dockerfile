# Product Agent — turns requirements into a product/experience definition (personas, journeys, IA,
# screen map). A thin FastAPI service like its siblings; it calls the active model on the host.
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY src/ ./src/
ENV PYTHONPATH=/app/src
CMD ["python3", "-m", "uvicorn", "product_agent.api:api", "--host", "0.0.0.0", "--port", "7809"]
