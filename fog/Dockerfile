FROM python:3.11-slim
WORKDIR /app
COPY ia/requirements-runtime.txt /app/requirements-runtime.txt
COPY fog/service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-runtime.txt -r requirements.txt
COPY fog/service/service.py /app/service.py
CMD ["python", "-u", "service.py"]
