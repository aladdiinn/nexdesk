"""
app.py — NexDesk
Flask routes only. Business logic lives in database.py and email_service.py.
"""
from flask import Flask, render_template, request, redirect, session, jsonify
from datetime import datetime

from database import (
    init_db, get_db,
    get_ticket, get_ticket_comments, get_ticket_activity, get_email_logs,
    get_agents, get_ticket_stats, get_email_tickets,
    generate_ticket_number, log_activity,
)
from email_service import (
    EMAIL_CONFIG, debug_log,
    send_email, send_ack_email, send_reply_email,
    process_email_message, start_poller,
    decode_str, extract_ticket_number, get_email_body, parse_sender,
)
import imaplib, email, traceback

app = Flask(__name__)
app.secret_key = "nexdesk-supersecret-2026"


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def require(*roles):
    return session.get("role") in roles


# ─────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=? AND is_active=1",
            (request.form["username"], request.form["password"])
        ).fetchone()
        conn.close()
        if user:
            session.update({
                "user_id":     user["id"],
                "username":    user["username"],
                "role":        user["role"],
                "full_name":   user["full_name"],
                "avatar_color":user["avatar_color"],
            })
            return redirect(
                "/admin/dashboard" if user["role"] == "admin" else
                "/agent/dashboard" if user["role"] == "agent" else
                "/portal/dashboard"
            )
        return render_template("login.html", error="Invalid credentials.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ─────────────────────────────────────────
#  PORTAL (app users)
# ─────────────────────────────────────────
@app.route("/portal/dashboard")
def portal_dashboard():
    if not require("app"): return redirect("/")
    conn = get_db()
    tickets = conn.execute(
        "SELECT * FROM tickets WHERE user_id=? AND source='web' ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    stats = {
        "open":       sum(1 for t in tickets if t["status"] == "Open"),
        "in_progress":sum(1 for t in tickets if t["status"] == "In Progress"),
        "resolved":   sum(1 for t in tickets if t["status"] in ("Resolved", "Closed")),
        "total":      len(tickets),
    }
    return render_template("portal_dashboard.html", tickets=tickets, stats=stats)


@app.route("/portal/tickets/<f>")
def portal_tickets_filter(f):
    return redirect("/portal/dashboard")


@app.route("/portal/ticket/<int:tid>")
def portal_ticket_detail(tid):
    if not require("app"): return redirect("/")
    conn = get_db()
    ticket = conn.execute(
        "SELECT * FROM tickets WHERE id=? AND user_id=?", (tid, session["user_id"])
    ).fetchone()
    conn.close()
    if not ticket: return redirect("/portal/dashboard")
    comments = get_ticket_comments(tid)
    # Filter internal from customer view
    comments = [c for c in comments if not c["is_internal"]]
    return render_template("portal_ticket_detail.html", ticket=ticket, comments=comments)


@app.route("/portal/ticket/<int:tid>/reply", methods=["POST"])
def portal_reply(tid):
    if not require("app"): return redirect("/")
    comment = request.form.get("comment", "").strip()
    if comment:
        conn = get_db()
        conn.execute("""INSERT INTO ticket_comments
            (ticket_id,user_id,sender_name,sender_email,comment,is_internal,comment_type)
            VALUES (?,?,?,?,?,0,'reply')""",
            (tid, session["user_id"], session["full_name"], "", comment))
        conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (datetime.now(), tid))
        conn.commit(); conn.close()
    return redirect(f"/portal/ticket/{tid}")


@app.route("/portal/raise", methods=["GET", "POST"])
def raise_ticket():
    if not require("app"): return redirect("/")
    if request.method == "POST":
        conn = get_db()
        tnum = generate_ticket_number(conn)
        conn.execute("""INSERT INTO tickets
            (ticket_number,user_id,source,requester_name,requester_email,subject,
             service_type,project_name,server_details,description,priority,category,tags,due_date)
            VALUES (?,?,'web',?,?,?,?,?,?,?,?,?,?,?)""",
            (tnum, session["user_id"], session["full_name"], "",
             request.form.get("service_type", "Support"),
             request.form["service_type"],
             request.form.get("project_name", ""),
             request.form.get("server_details", ""),
             request.form["description"],
             request.form.get("priority", "Medium"),
             request.form.get("category", "General"),
             request.form.get("tags", ""),
             request.form.get("due_date", "")))
        conn.commit(); conn.close()
        return redirect("/portal/dashboard")
    return render_template("raise_ticket.html")


# ─────────────────────────────────────────
#  AGENT
# ─────────────────────────────────────────
@app.route("/agent/dashboard")
def agent_dashboard():
    if not require("agent", "admin"): return redirect("/")
    conn = get_db()
    tickets = conn.execute("""SELECT t.*, COALESCE(u.full_name, t.requester_name) as req_name
        FROM tickets t LEFT JOIN users u ON t.user_id=u.id
        WHERE t.assigned_to=? ORDER BY t.created_at DESC""",
        (session["username"],)).fetchall()
    conn.close()
    stats = {
        "open":        sum(1 for t in tickets if t["status"] == "Open"),
        "in_progress": sum(1 for t in tickets if t["status"] == "In Progress"),
        "resolved":    sum(1 for t in tickets if t["status"] == "Resolved"),
        "total":       len(tickets),
    }
    return render_template("agent_dashboard.html", tickets=tickets, stats=stats)


@app.route("/agent/tickets")
def agent_tickets():
    return redirect("/agent/dashboard")


# ─────────────────────────────────────────
#  ADMIN — DASHBOARD & TICKET LIST
# ─────────────────────────────────────────
@app.route("/admin/dashboard")
def admin_dashboard():
    if not require("admin"): return redirect("/")
    return _ticket_list_view("", "", "", "")


@app.route("/admin/tickets")
def admin_tickets():
    if not require("admin"): return redirect("/")
    return _ticket_list_view(
        request.args.get("status", ""),
        request.args.get("priority", ""),
        request.args.get("assigned", ""),
        request.args.get("search", ""),
    )


def _ticket_list_view(status, priority, assigned, search):
    conn = get_db()
    q = """SELECT t.*,
        COALESCE(u.full_name, t.requester_name) as req_name,
        COALESCE(u.email,     t.requester_email) as req_email
        FROM tickets t LEFT JOIN users u ON t.user_id=u.id WHERE 1=1"""
    p = []
    if status:   q += " AND t.status=?";      p.append(status)
    if priority: q += " AND t.priority=?";    p.append(priority)
    if assigned: q += " AND t.assigned_to=?"; p.append(assigned)
    if search:
        q += """ AND (t.ticket_number LIKE ? OR t.description LIKE ?
                      OR t.subject LIKE ? OR t.requester_email LIKE ?)"""
        p.extend([f"%{search}%"] * 4)
    q += " ORDER BY t.created_at DESC"
    tickets = conn.execute(q, p).fetchall()
    agents  = get_agents()
    stats   = get_ticket_stats()
    conn.close()
    return render_template("admin_dashboard.html", tickets=tickets, stats=stats,
                           agents=agents, filter_status=status, filter_priority=priority,
                           filter_assigned=assigned, search=search)


# ─────────────────────────────────────────
#  ADMIN — TICKET DETAIL
# ─────────────────────────────────────────
@app.route("/admin/ticket/<int:tid>", methods=["GET", "POST"])
def admin_ticket_detail(tid):
    if not require("admin", "agent"): return redirect("/")
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update":
            status   = request.form["status"]
            priority = request.form["priority"]
            assigned = request.form["assigned_to"]
            meeting  = request.form.get("meeting_link", "").strip()

            conn.execute("""UPDATE tickets SET
                status=?, priority=?, assigned_to=?, category=?,
                due_date=?, resolution_note=?, meeting_link=?, updated_at=?
                WHERE id=?""",
                (status, priority, assigned,
                 request.form.get("category", "General"),
                 request.form.get("due_date", ""),
                 request.form.get("resolution_note", ""),
                 meeting, datetime.now(), tid))

            if meeting:
                conn.execute("""INSERT INTO ticket_comments
                    (ticket_id,user_id,sender_name,comment,comment_type,is_internal)
                    VALUES (?,?,?,?,'meeting',0)""",
                    (tid, session["user_id"], session["full_name"],
                     f"A meeting has been scheduled.\nJoin link: {meeting}"))

            log_activity(conn, tid, session["user_id"],
                f"Updated — status:{status}, priority:{priority}, assigned:{assigned or 'Unassigned'}")
            conn.commit()

            # Email customer if resolved
            ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
            if status in ("Resolved", "Closed") and ticket["requester_email"]:
                send_reply_email(
                    ticket["ticket_number"],
                    ticket["requester_name"] or "Customer",
                    ticket["requester_email"],
                    ticket["subject"] or ticket["ticket_number"],
                    f"Your ticket has been {status.lower()}.\n\n{request.form.get('resolution_note','')}",
                    session["full_name"]
                )

        elif action == "comment":
            comment  = request.form.get("comment", "").strip()
            internal = 1 if request.form.get("is_internal") else 0
            if comment:
                conn.execute("""INSERT INTO ticket_comments
                    (ticket_id,user_id,sender_name,comment,is_internal,comment_type)
                    VALUES (?,?,?,?,?,'reply')""",
                    (tid, session["user_id"], session["full_name"], comment, internal))
                conn.execute("UPDATE tickets SET updated_at=? WHERE id=?", (datetime.now(), tid))
                conn.commit()

                # Email customer (not for internal notes)
                if not internal:
                    ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
                    if ticket["requester_email"]:
                        send_reply_email(
                            ticket["ticket_number"],
                            ticket["requester_name"] or "Customer",
                            ticket["requester_email"],
                            ticket["subject"] or ticket["ticket_number"],
                            comment, session["full_name"]
                        )

        conn.close()
        return redirect(f"/admin/ticket/{tid}")

    # GET
    ticket     = get_ticket(tid)
    comments   = get_ticket_comments(tid)
    activity   = get_ticket_activity(tid)
    email_logs = get_email_logs(tid)
    agents     = get_agents()
    conn.close()
    return render_template("admin_ticket_detail.html", ticket=ticket, comments=comments,
                           activity=activity, agents=agents, email_logs=email_logs)


# ─────────────────────────────────────────
#  ADMIN CENTER & EMAIL CONFIG
# ─────────────────────────────────────────
@app.route("/admin/center")
def admin_center():
    if not require("admin"): return redirect("/")
    return render_template("admin_center.html",
                           email_enabled=EMAIL_CONFIG["enabled"],
                           support_email=EMAIL_CONFIG["support_email"])


@app.route("/admin/email/config", methods=["POST"])
def admin_email_config():
    if not require("admin"): return redirect("/")
    EMAIL_CONFIG["support_email"] = request.form["support_email"]
    EMAIL_CONFIG["username"]      = request.form["username"]
    EMAIL_CONFIG["password"]      = request.form["password"]
    EMAIL_CONFIG["smtp_host"]     = request.form.get("smtp_host", "smtp.gmail.com")
    EMAIL_CONFIG["imap_host"]     = request.form.get("imap_host", "imap.gmail.com")
    EMAIL_CONFIG["enabled"]       = "enabled" in request.form
    return redirect("/admin/center")


@app.route("/admin/email/test", methods=["POST"])
def admin_email_test():
    if not require("admin"): return redirect("/")
    to = request.form.get("test_email", "")
    ok = send_email(to, "NexDesk Test Email",
                    "<h2>✅ Email is working!</h2><p>NexDesk email config is correctly set up.</p>") if to else False
    return jsonify({"ok": ok})


# ─────────────────────────────────────────
#  EMAIL DEBUG & MANUAL INBOX CHECK
# ─────────────────────────────────────────
@app.route("/admin/email/debug")
def email_debug_page():
    if not require("admin"): return redirect("/")
    return render_template("email_debug.html", results=[], log=debug_log,
                           config=EMAIL_CONFIG, tickets_from_email=get_email_tickets())


@app.route("/admin/email/check")
def manual_check_inbox():
    if not require("admin"): return redirect("/")
    results = ["Starting manual inbox check..."]

    if not EMAIL_CONFIG["enabled"]:
        results.append("❌ Email is DISABLED. Set enabled=True in email_service.py and restart.")
        return render_template("email_debug.html", results=results, log=debug_log,
                               config=EMAIL_CONFIG, tickets_from_email=get_email_tickets())
    try:
        results.append(f"Connecting to {EMAIL_CONFIG['imap_host']}:{EMAIL_CONFIG['imap_port']}...")
        mail = imaplib.IMAP4_SSL(EMAIL_CONFIG["imap_host"], EMAIL_CONFIG["imap_port"])
        results.append("✅ IMAP connected")
        mail.login(EMAIL_CONFIG["username"], EMAIL_CONFIG["password"])
        results.append(f"✅ Logged in as {EMAIL_CONFIG['username']}")
        mail.select("INBOX")

        _, all_ids    = mail.search(None, "ALL")
        _, unseen_ids = mail.search(None, "UNSEEN")
        all_count     = len(all_ids[0].split())    if all_ids[0].strip()    else 0
        unseen_count  = len(unseen_ids[0].split()) if unseen_ids[0].strip() else 0
        results.append(f"📬 Inbox: {all_count} total, {unseen_count} unread")

        if unseen_count == 0:
            results.append("ℹ️ No unread emails. Send a test email then check again.")
        else:
            for mid in unseen_ids[0].split():
                _, data = mail.fetch(mid, "(RFC822)")
                status  = process_email_message(data[0][1])
                if status == "skip-own":
                    results.append("   ↳ Skipped (our own email)")
                elif status.startswith("created:"):
                    _, tnum, sender = status.split(":", 2)
                    results.append(f"   ↳ ✅ New ticket {tnum} created from {sender}")
                    results.append(f"   ↳ ✅ ACK email sent to {sender}")
                elif status.startswith("reply:"):
                    results.append(f"   ↳ ✅ Reply added to {status.split(':')[1]}")
                else:
                    results.append(f"   ↳ ⚠️ {status}")
                mail.store(mid, "+FLAGS", "\\Seen")

        mail.logout()
        results.append("✅ Done.")
    except Exception as e:
        results.append(f"❌ ERROR: {str(e)}")
        results.append(traceback.format_exc())

    return render_template("email_debug.html", results=results, log=debug_log,
                           config=EMAIL_CONFIG, tickets_from_email=get_email_tickets())


@app.route("/admin/email/simulate", methods=["POST"])
def simulate_email():
    if not require("admin"): return redirect("/")
    sender_name  = request.form.get("sender_name", "Test Customer")
    sender_email = request.form.get("sender_email", "test@example.com")
    subject      = request.form.get("subject", "Test Support Request")
    body         = request.form.get("body", "This is a test ticket from simulated email.")
    conn = get_db()
    tnum = generate_ticket_number(conn)
    conn.execute("""INSERT INTO tickets
        (ticket_number,user_id,source,requester_name,requester_email,
         subject,service_type,description,status,priority,category)
        VALUES (?,0,'email',?,?,?,'General',?,'Open','Medium','General')""",
        (tnum, sender_name, sender_email, subject, body))
    tid = conn.execute("SELECT id FROM tickets WHERE ticket_number=?", (tnum,)).fetchone()["id"]
    log_activity(conn, tid, 0, f"Ticket created from simulated email — {sender_email}")
    conn.commit(); conn.close()
    send_ack_email(tnum, sender_name, sender_email, subject, body)
    return redirect(f"/admin/ticket/{tid}")


# ─────────────────────────────────────────
#  ADMIN — USER MANAGEMENT
# ─────────────────────────────────────────
@app.route("/admin/users")
def admin_users():
    if not require("admin"): return redirect("/")
    fr   = request.args.get("role", "")
    conn = get_db()
    users = conn.execute(
        "SELECT * FROM users WHERE role=? ORDER BY created_at DESC", (fr,)
    ).fetchall() if fr else conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users, filter_role=fr,
                           message=request.args.get("msg", ""))


@app.route("/admin/users/add", methods=["GET", "POST"])
def admin_add_user():
    if not require("admin"): return redirect("/")
    if request.method == "POST":
        colors = {"admin": "#dc2626", "agent": "#059669", "app": "#2563eb"}
        role   = request.form["role"]
        try:
            conn = get_db()
            conn.execute("""INSERT INTO users
                (username,password,role,email,full_name,avatar_color)
                VALUES (?,?,?,?,?,?)""",
                (request.form["username"].strip(),
                 request.form["password"].strip(),
                 role,
                 request.form.get("email", "").strip(),
                 request.form["full_name"].strip(),
                 colors.get(role, "#2563eb")))
            conn.commit(); conn.close()
            return redirect("/admin/users?msg=User+created")
        except Exception as e:
            return render_template("admin_add_user.html", error=str(e))
    return render_template("admin_add_user.html")


@app.route("/admin/users/<int:uid>/role", methods=["POST"])
def admin_change_role(uid):
    if not require("admin"): return redirect("/")
    role   = request.form["role"]
    colors = {"admin": "#dc2626", "agent": "#059669", "app": "#2563eb"}
    conn   = get_db()
    conn.execute("UPDATE users SET role=?, avatar_color=? WHERE id=?",
                 (role, colors.get(role, "#2563eb"), uid))
    conn.commit(); conn.close()
    return redirect("/admin/users")


@app.route("/admin/users/<int:uid>/toggle", methods=["POST"])
def admin_toggle_user(uid):
    if not require("admin"): return redirect("/")
    conn = get_db()
    cur  = conn.execute("SELECT is_active FROM users WHERE id=?", (uid,)).fetchone()
    conn.execute("UPDATE users SET is_active=? WHERE id=?",
                 (0 if cur["is_active"] else 1, uid))
    conn.commit(); conn.close()
    return redirect("/admin/users")


@app.route("/admin/users/<int:uid>/reset_password", methods=["POST"])
def admin_reset_password(uid):
    if not require("admin"): return redirect("/")
    pw = request.form.get("new_password", "").strip()
    if pw:
        conn = get_db()
        conn.execute("UPDATE users SET password=? WHERE id=?", (pw, uid))
        conn.commit(); conn.close()
    return redirect("/admin/users")


# ─────────────────────────────────────────
#  START
# ─────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    start_poller()
    app.run(debug=True, use_reloader=False)
