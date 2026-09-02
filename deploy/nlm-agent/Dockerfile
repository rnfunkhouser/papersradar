# nlm-agent: one-shot vision-driven Gemini Notebook episode runner.
# Build from the REPO ROOT:  docker build -f deploy/nlm-agent/Dockerfile -t nlm-agent .
# Invoked per episode by pipeline/podcast.py (docker run --rm ...); auth
# storageState is mounted read-only from the notebooklm-data volume.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
# the image ships the browsers (/ms-playwright) but not the pip package for
# the system python — pin the wheel to the image's browser build
RUN pip install --no-cache-dir --break-system-packages playwright==1.49.1
COPY pipeline/nlm_agent.py /agent/nlm_agent.py
COPY deploy/nlm-agent/entrypoint.sh /agent/entrypoint.sh
# browser runs HEADFUL on Xvfb — Google bounces headless fingerprints to the
# login wall even with valid session cookies (measured 2026-09-01)
ENTRYPOINT ["/agent/entrypoint.sh"]
