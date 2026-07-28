"""CORS policy for Expo / React Native local and LAN development."""

from __future__ import annotations

import os

from flask import Flask
from flask_cors import CORS


def expo_cors_origins():
    """Origins for local Expo / React Native (PC + phone on LAN).

    Allows Metro/Expo ports, any localhost port, private LAN IPs, and optional
    ``EXPO_CORS_EXTRA_ORIGINS``. Set ``CORS_ALLOW_ALL_ORIGINS=1`` only for local
    debugging—never in production.
    """
    if os.environ.get("CORS_ALLOW_ALL_ORIGINS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return "*"

    origins: list = [
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:19000",
        "http://127.0.0.1:19000",
        "http://localhost:19006",
        "http://127.0.0.1:19006",
        r"^http://localhost:\d+$",
        r"^http://127\.0\.0\.1:\d+$",
        r"^http://\[::1\]:\d+$",
        r"^http://192\.168\.\d{1,3}\.\d{1,3}:\d+$",
        r"^http://10\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$",
        r"^http://172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}:\d+$",
        "null",
    ]
    for raw in os.environ.get("EXPO_CORS_EXTRA_ORIGINS", "").split(","):
        o = raw.strip()
        if o:
            origins.append(o)
    return origins


def init_cors(app: Flask) -> None:
    CORS(
        app,
        origins=expo_cors_origins(),
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        # Request allow-list must match Hypatia frontend httpClient.ts headers:
        # Accept, Cache-Control, Pragma, X-Request-ID always; Content-Type on
        # JSON bodies; Authorization when a Bearer token is supplied.
        # expose_headers only covers response readability (X-Request-ID echo).
        allow_headers=[
            "Accept",
            "Authorization",
            "Cache-Control",
            "Content-Type",
            "Pragma",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
    )
