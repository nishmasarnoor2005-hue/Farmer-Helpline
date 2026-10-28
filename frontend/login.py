"""
frontend/login.py

Admin authentication helpers for the Flask-Login integration.
Credentials are sourced from environment variables only — never hardcoded.
"""

import logging
import os

from flask_login import UserMixin
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)


class AdminUser(UserMixin):
    """Single admin identity used by Flask-Login."""
    id = "admin"


def verify_admin(username: str, password: str) -> "AdminUser | None":
    """
    Validate username/password against env-var stored credentials.

    Returns an AdminUser on success, None on any failure.
    Never raises.
    """
    expected_username = os.environ.get("ADMIN_USERNAME")
    expected_hash = os.environ.get("ADMIN_PASSWORD_HASH")

    if not expected_username or not expected_hash:
        logger.warning("ADMIN_USERNAME or ADMIN_PASSWORD_HASH not set")
        return None

    if username == expected_username and check_password_hash(expected_hash, password):
        return AdminUser()

    return None
