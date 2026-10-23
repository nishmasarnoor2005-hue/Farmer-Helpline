# NOTE: This file is NOT used by the Flask app (app.py).
# The Flask app does not use SQLite for call sessions.
# This module creates the farmer profile database schema and is
# kept for future use (e.g. a dashboard or admin panel).

import sqlite3

def create_database():
    conn = sqlite3.connect("database/farmer.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS farmers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        state TEXT,
        district TEXT,
        language TEXT
    )
    """)

    conn.commit()
    conn.close()

create_database()