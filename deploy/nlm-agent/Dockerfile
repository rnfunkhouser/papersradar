# nlm-agent: one-shot vision-driven Gemini Notebook episode runner.
# Build from the REPO ROOT:  docker build -f deploy/nlm-agent/Dockerfile -t nlm-agent .
# Invoked per episode by pipeline/podcast.py (docker run --rm ...); auth
# storageState is mounted read-only from the notebooklm-data volume.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
COPY pipeline/nlm_agent.py /agent/nlm_agent.py
ENTRYPOINT ["python3", "/agent/nlm_agent.py"]
