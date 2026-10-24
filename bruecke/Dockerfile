# FILE: bruecke/Dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ablage.py ./
RUN groupadd -r bruecke && useradd -r -g bruecke bruecke && mkdir -p /data && chown -R bruecke:bruecke /data
USER bruecke
EXPOSE 9000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000", "--no-access-log"]
# END: bruecke/Dockerfile
