FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install backend Python dependencies from the repo root build context.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt playwright==1.49.0

# Copy only the backend application into the image.
COPY backend/ .

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_ENABLED=true

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
