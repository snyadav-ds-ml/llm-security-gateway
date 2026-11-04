import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("AUDIT_DB_PATH", "./audit.db")

def init_db():
    # creates the table if it doesn't exist — safe to call on every startup
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                question     TEXT NOT NULL,
                answer       TEXT,
                blocked      INTEGER DEFAULT 0,
                block_reason TEXT
            )
        """)

        # new ingest_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_log 
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                provenance TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                outlier_distance REAL
            )


        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_call_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                tool_name   TEXT NOT NULL,
                tool_input  TEXT NOT NULL,
                blocked     INTEGER DEFAULT 0,
                block_reason TEXT
            )
        """)

def log_tool_call(tool_name, tool_input, blocked=False, block_reason=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tool_call_log (timestamp, tool_name, tool_input, blocked, block_reason) VALUES (?,?,?,?,?)" ,
            (datetime.now(timezone.utc).isoformat(), tool_name, str(tool_input), int(blocked), block_reason)
        )

def log_ingest(source, provenance, decision, reason, outlier_distance):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
           "INSERT INTO ingest_log (timestamp, source, provenance, decision, reason, outlier_distance) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), source, provenance, decision, reason, outlier_distance) 
        )


def log_request(question: str, answer: str, blocked: bool = False, block_reason: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, question, answer, blocked, block_reason) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), question, answer, int(blocked), block_reason)
        )