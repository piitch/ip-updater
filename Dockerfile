FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    IPUPDATER_CONFIG=/config/config.yaml \
    IPUPDATER_STATE=/data/state.json

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ipupdater ./ipupdater
RUN mkdir -p /config /data

VOLUME ["/config", "/data"]
ENTRYPOINT ["python", "-m", "ipupdater"]
CMD ["run"]
