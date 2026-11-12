# CC TV — Cloud Container Dockerfile
FROM python:3.11-slim

# Install system dependencies for OpenCV and video handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure storage directories exist
RUN mkdir -p recordings snapshots

# Expose server port
EXPOSE 8080

ENV PORT=8080
ENV HOST=0.0.0.0

CMD ["python", "app.py"]
