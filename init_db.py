import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "database.db")

print("INIT DB PATH:", db_path)

conn = sqlite3.connect(db_path)
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

# Create admin
cursor.execute("""
INSERT OR IGNORE INTO users (username, password_hash, hourly_rate, role)
VALUES (?, ?, ?, ?)
""", (
    "admin",
    generate_password_hash("admin123"),
    0.0,
    "admin"
))

# Create employee
cursor.execute("""
INSERT OR IGNORE INTO users (username, password_hash, hourly_rate, role)
VALUES (?, ?, ?, ?)
""", (
    "john",
    generate_password_hash("1234"),
    20.0,
    "employee"
))

conn.commit()
conn.close()

print("Database initialized successfully.")
