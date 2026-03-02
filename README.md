# NexDesk — Cloud Support Ticketing System

## Project Structure

```
nexdesk/
│
├── app.py              ← Flask routes only (thin controller layer)
├── database.py         ← All SQLite DB logic (init, queries, helpers)
├── email_service.py    ← All email logic (SMTP send, IMAP poll, templates)
├── requirements.txt    ← pip dependencies
│
└── templates/          ← Jinja2 HTML templates
    ├── base.html                  ← Layout with dual sidebar (BoldDesk style)
    ├── login.html
    ├── portal_dashboard.html      ← App user: my tickets
    ├── portal_ticket_detail.html  ← App user: view ticket + reply
    ├── raise_ticket.html          ← App user: raise new ticket
    ├── agent_dashboard.html       ← Agent: assigned tickets queue
    ├── admin_dashboard.html       ← Admin: all tickets + filters
    ├── admin_ticket_detail.html   ← Admin: manage ticket, reply, log
    ├── admin_center.html          ← Admin: settings, email config
    ├── admin_users.html           ← Admin: user management
    ├── admin_add_user.html        ← Admin: add new user
    └── email_debug.html           ← Admin: email debug + manual check
```

## Setup

```bash
pip install flask
del tickets.db        # Windows — delete old DB on schema changes
python app.py
```

## Email Config

Edit `email_service.py` top section:

```python
EMAIL_CONFIG = {
    "support_email": "your-support@gmail.com",
    "username":      "your-support@gmail.com",
    "password":      "xxxx xxxx xxxx xxxx",   # Gmail App Password
    "enabled":       True,
}
```

## Demo Accounts

| Role  | Username   | Password |
|-------|------------|----------|
| Admin | adminuser  | 123      |
| Agent | agent1     | 123      |
| User  | appuser    | 123      |

## Key URLs

| URL                        | Description               |
|----------------------------|---------------------------|
| /                          | Login                     |
| /admin/dashboard           | Admin ticket list         |
| /admin/email/debug         | Email debug console       |
| /admin/email/check         | Manual inbox check        |
| /admin/center              | Admin center + email cfg  |
| /admin/users               | User management           |
| /agent/dashboard           | Agent queue               |
| /portal/dashboard          | Customer portal           |
