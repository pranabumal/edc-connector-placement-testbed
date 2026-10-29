FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000
# waitress: one process (the TC-4 alert state is in memory), threads, HTTP/1.1 keep-alive
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=16", "app:app"]
