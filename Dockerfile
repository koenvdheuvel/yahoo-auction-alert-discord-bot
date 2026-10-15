FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "healthcheck.py"]
CMD ["python", "main.py"]
