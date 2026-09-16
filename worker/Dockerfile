FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# Unbuffered stdout so `docker logs` shows progress lines as they happen,
# not only after the buffer flushes.
ENV PYTHONUNBUFFERED=1

CMD ["python", "worker.py"]
