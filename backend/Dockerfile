FROM python:3.12-slim
WORKDIR /app

# IMPORTANT: NOT using 3.14 because the latter doesn't have Rust compiler provided natively
# Would require adding something like 
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends \
#        build-essential \
#        gcc \
#    && rm -rf /var/lib/apt/lists/*

# Curl required because used from inside container to make healthchecks by requesting /health.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "app.main"]
