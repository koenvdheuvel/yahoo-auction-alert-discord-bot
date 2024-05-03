FROM python:3.11-alpine as build

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-OO", "main.py"]