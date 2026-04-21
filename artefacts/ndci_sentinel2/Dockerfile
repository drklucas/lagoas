FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema
# psycopg2: libpq-dev + gcc
# WeasyPrint: libcairo2, libpango*, libgdk-pixbuf2.0-0, libffi-dev, fontes
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
