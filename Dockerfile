FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and its system dependencies (runs as root during build)
RUN playwright install --with-deps chromium

COPY . .

RUN mkdir -p data

CMD ["python", "main.py"]
