FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir uv && uv sync

ENV PYTHONPATH=/app/src

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5001/health', timeout=3).status == 200 else 1)"

CMD ["uv", "run", "-m", "radarr_sonarr_jellyfin_notifier"]
