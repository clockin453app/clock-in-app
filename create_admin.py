import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    hourly_rate REAL NOT NULL,
    role TEXT NOT NULL
)
""")

cursor.execute("""
INSERT INTO users (username, password_hash, hourly_rate, role)
VALUES (?, ?, ?, ?)
""", (
    "admin",
    generate_password_hash("admin123"),
    0.0,
    "admin"
))

conn.commit()
conn.close()

print("Admin created successfully.")
