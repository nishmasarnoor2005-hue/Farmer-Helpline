"""
wsgi.py — Gunicorn entry point.

Gevent monkey-patching MUST happen before any other import,
especially before ssl, aiohttp, urllib3 import.
This file exists solely to ensure patch_all() runs first.
"""
# Step 1: monkey-patch everything before any other import
try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass  # local dev without gevent

# Step 2: now import the Flask app (all its imports happen after patching)
from app import app  # noqa: E402 — intentional late import

__all__ = ["app"]
