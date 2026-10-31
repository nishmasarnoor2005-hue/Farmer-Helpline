"""
wsgi.py — Gunicorn entry point.

Uses gthread worker (--worker-class gthread) which supports flask-sock
WebSockets natively without gevent.

gevent 24.11.1 is NOT used because it has a hardcoded assertion:
    assert sys.version_info[:2] < (3, 13)
which crashes on Render's Python 3.14 runtime.
"""
from app import app  # noqa: F401

__all__ = ["app"]
