"""Compatibility entrypoint: ``app`` for WSGI/CLI/tests, ``python app.py`` for local dev."""

from __future__ import annotations

import os

from hypatia import create_app

app = create_app()


if __name__ == "__main__":
    app.run(
        debug=app.config["DEBUG"],
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5001")),
    )
