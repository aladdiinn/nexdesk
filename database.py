"""
database.py — NexDesk
All database initialization, connection, and query helpers.
"""
import sqlite3
from datetime import datetime

DATABASE = "tickets.db"


# ─────────────────────────────────────────
#  CONNECTION
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────
#  INIT — creates all tables + demo users
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE,
        password      TEXT,
        role          TEXT,
        email         TEXT,
        full_name     TEXT,
        avatar_color  TEXT    DEFAULT '#2563eb',
        is_active     INTEGER DEFAULT 1,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tickets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_number   TEXT UNIQUE,
        user_id         INTEGER,
        source          TEXT    DEFAULT 'web',
        requester_name  TEXT    DEFAULT '',
        requester_email TEXT    DEFAULT '',
        subject         TEXT    DEFAULT '',
        service_type    TEXT    DEFAULT 'General',
        project_name    TEXT,
        server_details  TEXT,
        description     TEXT,
        status          TEXT    DEFAULT 'Open',
        priority        TEXT    DEFAULT 'Medium',
        assigned_to     TEXT,
        category        TEXT    DEFAULT 'General',
        tags            TEXT    DEFAULT '',
        due_date        TEXT,
        resolution_note TEXT,
        meeting_link    TEXT    DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS ticket_comments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id     INTEGER,
        user_id       INTEGER,
        sender_name   TEXT DEFAULT '',
        sender_email  TEXT DEFAULT '',
        comment       TEXT,
        comment_type  TEXT DEFAULT 'reply',
        is_internal   INTEGER DEFAULT 0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS ticket_activity (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id  INTEGER,
        user_id    INTEGER,
        action     TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id  INTEGER,
        direction  TEXT,
        to_email   TEXT,
        subject    TEXT,
        status     TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # Demo users (only inserted if not already present)
    demo_users = [
        ("appuser",   "123", "app",   "app@company.com",   "App User",      "#2563eb"),
        ("adminuser", "123", "admin", "admin@company.com", "Admin User",    "#dc2626"),
        ("agent1",    "123", "agent", "agent1@company.com","Sarah Johnson", "#059669"),
        ("agent2",    "123", "agent", "agent2@company.com","Mike Chen",     "#d97706"),
    ]
    for u in demo_users:
        c.execute("SELECT id FROM users WHERE username=?", (u[0],))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (username,password,role,email,full_name,avatar_color)
                VALUES (?,?,?,?,?,?)""", u)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────
#  TICKET HELPERS
# ─────────────────────────────────────────
def generate_ticket_number(conn):
    """Returns next TKT-XXXXX number."""
    last = conn.execute("SELECT id FROM tickets ORDER BY id DESC LIMIT 1").fetchone()
    return f"TKT-{(last['id'] + 1 if last else 1):05d}"


def get_ticket(tid):
    conn = get_db()
    ticket = conn.execute("""
        SELECT t.*,
            COALESCE(u.full_name, t.requester_name) as req_name,
            COALESCE(u.email,     t.requester_email) as req_email
        FROM tickets t LEFT JOIN users u ON t.user_id = u.id
        WHERE t.id = ?""", (tid,)).fetchone()
    conn.close()
    return ticket


def get_ticket_comments(tid):
    conn = get_db()
    rows = conn.execute("""
        SELECT tc.*,
            COALESCE(u.full_name,    tc.sender_name) as display_name,
            COALESCE(u.avatar_color, '#94a3b8')       as avatar_color,
            COALESCE(u.role,         'customer')       as user_role
        FROM ticket_comments tc
        LEFT JOIN users u ON tc.user_id = u.id
        WHERE tc.ticket_id = ?
        ORDER BY tc.created_at ASC""", (tid,)).fetchall()
    conn.close()
    return rows


def get_ticket_activity(tid):
    conn = get_db()
    rows = conn.execute("""
        SELECT ta.*, COALESCE(u.full_name, 'System') as full_name
        FROM ticket_activity ta
        LEFT JOIN users u ON ta.user_id = u.id
        WHERE ta.ticket_id = ?
        ORDER BY ta.created_at DESC LIMIT 20""", (tid,)).fetchall()
    conn.close()
    return rows


def get_email_logs(tid):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM email_log WHERE ticket_id=? ORDER BY created_at DESC", (tid,)
    ).fetchall()
    conn.close()
    return rows


def get_agents():
    conn = get_db()
    rows = conn.execute(
        "SELECT username, full_name FROM users WHERE role IN ('agent','admin') AND is_active=1"
    ).fetchall()
    conn.close()
    return rows


def get_ticket_stats():
    conn = get_db()
    all_t = conn.execute("SELECT status, source FROM tickets").fetchall()
    stats = {
        "total":       len(all_t),
        "open":        sum(1 for t in all_t if t["status"] == "Open"),
        "in_progress": sum(1 for t in all_t if t["status"] == "In Progress"),
        "resolved":    sum(1 for t in all_t if t["status"] == "Resolved"),
        "closed":      sum(1 for t in all_t if t["status"] == "Closed"),
        "email":       sum(1 for t in all_t if t["source"] == "email"),
        "web":         sum(1 for t in all_t if t["source"] == "web"),
    }
    conn.close()
    return stats


def log_activity(conn, ticket_id, user_id, action):
    conn.execute(
        "INSERT INTO ticket_activity (ticket_id, user_id, action) VALUES (?,?,?)",
        (ticket_id, user_id, action)
    )


def log_email(ticket_id, direction, to_email, subject, status):
    conn = get_db()
    conn.execute(
        "INSERT INTO email_log (ticket_id,direction,to_email,subject,status) VALUES (?,?,?,?,?)",
        (ticket_id, direction, to_email, subject, status)
    )
    conn.commit()
    conn.close()


def get_email_tickets(limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tickets WHERE source='email' ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
