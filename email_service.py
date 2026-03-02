"""
email_service.py — NexDesk
All email sending (SMTP), receiving (IMAP), parsing, and polling logic.
"""
import smtplib, imaplib, email, re, time, threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header

# ─────────────────────────────────────────
#  CONFIG  (edit these before running)
# ─────────────────────────────────────────
EMAIL_CONFIG = {
    "support_email": "dummytds3@gmail.com",
    "username":      "dummytds3@gmail.com",
    "password":      "ckqg dbih mdhb dujp",   # Gmail App Password
    "smtp_host":     "smtp.gmail.com",
    "smtp_port":     587,
    "imap_host":     "imap.gmail.com",
    "imap_port":     993,
    "poll_interval": 60,      # seconds between inbox checks
    "enabled":       True,    # set False to disable email completely
}

# In-memory debug log (last 100 lines)
debug_log = []


# ─────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────
def log(msg):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    debug_log.insert(0, line)
    if len(debug_log) > 100:
        debug_log.pop()


# ─────────────────────────────────────────
#  SMTP — SEND
# ─────────────────────────────────────────
def send_email(to_email, subject, html_body, ticket_id=None):
    """Send an HTML email. Returns True on success."""
    if not EMAIL_CONFIG["enabled"]:
        log(f"[EMAIL DISABLED] Would send to {to_email}: {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"NexDesk Support <{EMAIL_CONFIG['support_email']}>"
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["smtp_host"], EMAIL_CONFIG["smtp_port"], timeout=15) as s:
            s.starttls()
            s.login(EMAIL_CONFIG["username"], EMAIL_CONFIG["password"])
            s.sendmail(EMAIL_CONFIG["support_email"], to_email, msg.as_string())

        log(f"[EMAIL SENT] To:{to_email} | {subject}")

        if ticket_id:
            from database import log_email
            log_email(ticket_id, "outbound", to_email, subject, "sent")

        return True
    except Exception as e:
        log(f"[EMAIL ERROR] {e}")
        return False


# ─────────────────────────────────────────
#  EMAIL TEMPLATES
# ─────────────────────────────────────────
def send_ack_email(ticket_number, requester_name, requester_email, subject, description, priority="Medium"):
    """Send acknowledgement email when a new ticket is created."""
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:24px 32px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:22px;font-weight:800;color:white;">🎫 NexDesk</div>
        <div style="color:rgba(255,255,255,.7);font-size:13px;">Cloud Support Platform</div>
      </td>
      <td align="right">
        <div style="background:rgba(255,255,255,.15);color:white;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:700;">
          Acknowledgement
        </div>
      </td>
    </tr></table>
  </td></tr>
  <!-- Body -->
  <tr><td style="padding:32px;">
    <p style="font-size:15px;color:#1e293b;margin:0 0 8px;">Dear <strong>{requester_name}</strong>,</p>
    <p style="font-size:14px;color:#475569;line-height:1.7;margin:0 0 24px;">
      Thank you for contacting <strong>NexDesk Support</strong>. We have received your request
      and a support ticket has been created. Our team will review it and get back to you shortly.
    </p>
    <!-- Ticket Details Box -->
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:24px;">
    <tr><td style="padding:20px 24px;">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:14px;">
        Ticket Details
      </div>
      <table width="100%">
        <tr>
          <td width="40%" style="padding:6px 0;font-size:13px;color:#64748b;font-weight:600;">Ticket ID</td>
          <td style="padding:6px 0;font-size:14px;color:#2563eb;font-weight:800;font-family:monospace;">{ticket_number}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#64748b;font-weight:600;border-top:1px solid #e2e8f0;">Subject</td>
          <td style="padding:6px 0;font-size:13px;color:#1e293b;border-top:1px solid #e2e8f0;">{subject}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#64748b;font-weight:600;border-top:1px solid #e2e8f0;">Status</td>
          <td style="padding:6px 0;border-top:1px solid #e2e8f0;">
            <span style="background:#fffbeb;color:#b45309;border:1px solid #fde68a;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:700;">
              Open
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#64748b;font-weight:600;border-top:1px solid #e2e8f0;">Priority</td>
          <td style="padding:6px 0;font-size:13px;color:#1e293b;border-top:1px solid #e2e8f0;">{priority}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:13px;color:#64748b;font-weight:600;border-top:1px solid #e2e8f0;">Created At</td>
          <td style="padding:6px 0;font-size:13px;color:#1e293b;border-top:1px solid #e2e8f0;">
            {datetime.now().strftime('%d %b %Y, %I:%M %p')}
          </td>
        </tr>
      </table>
    </td></tr></table>
    <!-- Message Preview -->
    <div style="background:#f0f9ff;border-left:4px solid #2563eb;padding:14px 18px;border-radius:0 6px 6px 0;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#2563eb;margin-bottom:6px;">
        Your Message
      </div>
      <div style="font-size:13.5px;color:#334155;line-height:1.7;">
        {description[:400]}{"..." if len(description) > 400 else ""}
      </div>
    </div>
    <p style="font-size:13.5px;color:#475569;line-height:1.7;margin:0;">
      Please keep your <strong>Ticket ID ({ticket_number})</strong> handy for all future correspondence.
      You can reply to this email to add more information — keep the Ticket ID in the subject line.
    </p>
  </td></tr>
  <!-- Footer -->
  <tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 32px;text-align:center;">
    <p style="font-size:12px;color:#94a3b8;margin:0;">
      This is an automated acknowledgement from <strong>NexDesk Support</strong>.
    </p>
  </td></tr>
</table></td></tr></table></body></html>"""

    return send_email(
        requester_email,
        f"[{ticket_number}] Ticket Received — {subject}",
        html
    )


def send_reply_email(ticket_number, requester_name, requester_email, subject, reply_text, agent_name):
    """Send agent reply email to customer."""
    html = f"""<!DOCTYPE html><html>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <tr><td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:20px 32px;">
    <div style="font-size:20px;font-weight:800;color:white;">🎫 NexDesk Support</div>
  </td></tr>
  <tr><td style="padding:28px 32px;">
    <div style="background:#eff6ff;border:1px solid #dbeafe;border-radius:6px;
                padding:10px 14px;margin-bottom:20px;font-size:12px;color:#2563eb;
                font-family:monospace;font-weight:700;">
      Re: [{ticket_number}] {subject}
    </div>
    <p style="font-size:15px;color:#1e293b;margin:0 0 6px;">Dear <strong>{requester_name}</strong>,</p>
    <p style="font-size:13.5px;color:#475569;margin:0 0 20px;">Our support team has responded to your ticket:</p>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:18px 22px;margin-bottom:20px;font-size:13.5px;color:#1e293b;line-height:1.75;">
      {reply_text}
    </div>
    <p style="font-size:12.5px;color:#64748b;margin:0;">
      — <strong>{agent_name}</strong>, NexDesk Support<br>
      <span style="color:#94a3b8;">
        Ticket ID: {ticket_number} | Keep this ID in your subject line for follow-up.
      </span>
    </p>
  </td></tr>
  <tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:14px 32px;text-align:center;">
    <p style="font-size:11.5px;color:#94a3b8;margin:0;">NexDesk Support Platform</p>
  </td></tr>
</table></td></tr></table></body></html>"""

    return send_email(
        requester_email,
        f"Re: [{ticket_number}] {subject}",
        html
    )


# ─────────────────────────────────────────
#  IMAP — PARSE INCOMING EMAIL
# ─────────────────────────────────────────
def decode_str(s):
    if s is None: return ""
    parts = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(part))
    return " ".join(parts)


def extract_ticket_number(subject):
    """Returns TKT-XXXXX if found in subject, else None."""
    m = re.search(r'TKT-\d{5}', subject or "")
    return m.group(0) if m else None


def get_email_body(msg):
    """Extract plain text body, strip quoted replies."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    break
                except: pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace")
        except:
            body = str(msg.get_payload())
    lines = [l for l in body.split('\n') if not l.strip().startswith('>')]
    return '\n'.join(lines).strip()[:3000]


def parse_sender(from_header):
    """Returns (name, email) from a From: header."""
    m = re.match(r'^(.*?)\s*<(.+?)>$', from_header.strip())
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip()
    return from_header.strip(), from_header.strip()


def process_email_message(msg_bytes):
    """
    Parse one raw email and create or update a ticket.
    Returns a status string: 'skip-own', 'created:TKT-XXXXX:email', 'reply:TKT-XXXXX', etc.
    """
    from database import get_db, generate_ticket_number, log_activity

    msg          = email.message_from_bytes(msg_bytes)
    subject      = decode_str(msg.get("Subject", "(No Subject)"))
    from_header  = decode_str(msg.get("From", ""))
    body         = get_email_body(msg)
    sender_name, sender_email = parse_sender(from_header)

    # Skip emails sent by ourselves
    if sender_email.lower() == EMAIL_CONFIG["support_email"].lower():
        return "skip-own"

    conn = get_db()
    existing_tkt = extract_ticket_number(subject)

    if existing_tkt:
        # Reply to an existing ticket
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE ticket_number=?", (existing_tkt,)
        ).fetchone()
        if ticket:
            conn.execute("""INSERT INTO ticket_comments
                (ticket_id,user_id,sender_name,sender_email,comment,comment_type,is_internal)
                VALUES (?,0,?,?,?,'email',0)""",
                (ticket["id"], sender_name, sender_email, body))
            conn.execute(
                "UPDATE tickets SET updated_at=?, status='Open' WHERE id=?",
                (datetime.now(), ticket["id"])
            )
            conn.commit(); conn.close()
            return f"reply:{existing_tkt}"
        conn.close()
        return f"reply-notfound:{existing_tkt}"
    else:
        # Brand new ticket from email
        tnum = generate_ticket_number(conn)
        conn.execute("""INSERT INTO tickets
            (ticket_number, user_id, source, requester_name, requester_email,
             subject, service_type, description, status, priority, category)
            VALUES (?,0,'email',?,?,?,'General',?,'Open','Medium','General')""",
            (tnum, sender_name, sender_email, subject, body))
        tid = conn.execute(
            "SELECT id FROM tickets WHERE ticket_number=?", (tnum,)
        ).fetchone()["id"]
        log_activity(conn, tid, 0, f"Ticket created from email — {sender_email}")
        conn.commit(); conn.close()

        send_ack_email(tnum, sender_name, sender_email, subject, body)
        return f"created:{tnum}:{sender_email}"


# ─────────────────────────────────────────
#  BACKGROUND IMAP POLLER
# ─────────────────────────────────────────
def poll_inbox():
    """Runs in a daemon thread. Checks inbox every poll_interval seconds."""
    while True:
        if not EMAIL_CONFIG["enabled"]:
            time.sleep(30)
            continue
        try:
            log("[POLL] Checking inbox...")
            mail = imaplib.IMAP4_SSL(EMAIL_CONFIG["imap_host"], EMAIL_CONFIG["imap_port"])
            mail.login(EMAIL_CONFIG["username"], EMAIL_CONFIG["password"])
            mail.select("INBOX")

            _, ids = mail.search(None, "UNSEEN")
            count  = len(ids[0].split()) if ids[0].strip() else 0
            log(f"[POLL] {count} unread email(s) found")

            for mid in ids[0].split():
                _, data = mail.fetch(mid, "(RFC822)")
                result  = process_email_message(data[0][1])
                log(f"[POLL] → {result}")
                mail.store(mid, "+FLAGS", "\\Seen")

            mail.logout()
        except Exception as e:
            log(f"[POLL ERROR] {e}")
        time.sleep(EMAIL_CONFIG["poll_interval"])


def start_poller():
    """Start the background email polling thread."""
    t = threading.Thread(target=poll_inbox, daemon=True)
    t.start()
    log(f"[EMAIL] Poller started — enabled:{EMAIL_CONFIG['enabled']} | account:{EMAIL_CONFIG['support_email']}")
