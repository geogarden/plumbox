"""Uruchamianie Uvicorn zgodnie z config.yaml."""

from __future__ import annotations

import os

import uvicorn

from .config import load_config


def main() -> None:
    config_path = os.environ.get("PLUMBOX_CONFIG", "/etc/plumbox/config.yaml")
    config = load_config(config_path)
    uvicorn.run(
        "app.main:app",
        host=config.web.host,
        port=config.web.port,
        proxy_headers=True,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
