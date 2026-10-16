# The dashboard's UI is built in this stage. Only the built files go into the bot image.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# The bot's files without the UI source. The legacy builder has no COPY --exclude, so the
# source is removed in a stage of its own and never reaches a layer of the final image.
FROM python:3.11-slim AS source
COPY . /src
RUN rm -rf /src/frontend

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=source /src /app
COPY --from=frontend /frontend/dist /app/frontend/dist

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "healthcheck.py"]
CMD ["python", "main.py"]
