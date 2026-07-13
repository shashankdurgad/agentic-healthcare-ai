FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY overmind_demo/crewai_service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY overmind_demo/crewai_service /app
COPY overmind_demo/fixtures /app/fixtures

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV CREWAI_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -sf http://localhost:8090/health || exit 1

CMD ["python", "main.py"]
