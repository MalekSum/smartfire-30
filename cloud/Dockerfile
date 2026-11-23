FROM python:3.11-slim
WORKDIR /app
COPY ia/requirements-runtime.txt /app/requirements-runtime.txt
COPY cloud/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-runtime.txt -r requirements.txt
COPY cloud/main.py /app/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
