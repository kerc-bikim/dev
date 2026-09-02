FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir redis==5.2.1
COPY apps/worker/worker.py /app/worker.py
CMD ["python", "/app/worker.py"]
