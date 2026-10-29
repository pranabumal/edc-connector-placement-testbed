FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY adapter.py .
EXPOSE 8099
CMD ["python", "adapter.py"]
