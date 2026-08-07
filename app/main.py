"""Papers Radar web app. Run locally:

    uvicorn app.main:app --reload

Production (systemd unit in deploy/): single worker, 127.0.0.1:8000 behind
Caddy. Resident memory budget ~<150 MB — no numpy/torch imports here.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import log_dir


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(log_dir() / "web.log")])
    application = FastAPI(title="Papers Radar", docs_url=None, redoc_url=None,
                          openapi_url=None)
    from app import routes_public, routes_user, routes_admin, routes_zotero
    application.include_router(routes_public.router)
    application.include_router(routes_user.router)
    application.include_router(routes_admin.router)
    application.include_router(routes_zotero.router)
    application.mount("/static",
                      StaticFiles(directory=str(Path(__file__).parent / "static")),
                      name="static")
    return application


app = create_app()
