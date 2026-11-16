FROM python:3.15-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 zlib1g && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt && useradd --system --uid 10001 aegis
COPY aegis ./aegis
USER 10001
CMD ["python","-m","uvicorn","aegis.api:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log","--no-proxy-headers"]
