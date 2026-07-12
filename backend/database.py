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