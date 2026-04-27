# Single-process container: Streamlit on 8501, auto-spawns Flask on 5000.
# We don't expose 5000 externally because the Streamlit frontend talks to
# Flask over loopback inside the container. This keeps the surface small
# (one port, one entry point) without losing the auth gate.

FROM python:3.11-slim AS base

# Smaller layer cache + reproducible behaviour.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Streamlit defaults that make it container-friendly.
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

# tini is a tiny init that reaps zombie children + forwards signals.
# Streamlit spawns the Flask thread inside its own process so a true
# init isn't strictly required, but it makes Ctrl-C / docker stop
# behave correctly with under 1 MB of overhead.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so source-only changes hit a warm pip cache.
COPY ikigai_masala-main/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Copy the rest of the app. .dockerignore keeps tests / docs / .git / etc.
# out of the image.
COPY ikigai_masala-main/ ./

# Run as a non-root user — defence in depth even though the container
# only listens on a Streamlit socket.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
 && chown -R app:app /app
USER app

EXPOSE 8501

# Liveness probe hits the Flask backend's /health (auto-spawned by
# Streamlit). 503 = "Supabase unreachable", which is still up enough
# for the orchestrator to consider the container alive — the real
# readiness signal is the response body. Use --fail to exit non-zero
# on 5xx; orchestrators that want stricter readiness can replace this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:5000/api/v1/health \
       || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["streamlit", "run", "app.py"]
