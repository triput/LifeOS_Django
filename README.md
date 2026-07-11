<!--
# ==============================================================================
# File: README.md
# Description: Bootstrap and documentation index for LifeOS V2
# Component: Documentation
# Version: 2.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-07-10
# ==============================================================================
-->

# LifeOS V2 — Personal Cockpit

Single-owner personal operating system: calm Home canvas, Cmd+K gateway, deep surfaces on demand. Django SSR + HTMX + thin Alpine; SQLite or PostgreSQL.

**Authoritative spec:** [docs/LIFEOSV2_Alternate_SRS.md](docs/LIFEOSV2_Alternate_SRS.md)

---

## Documentation

| Doc | Audience |
| :--- | :--- |
| [User Guide](docs/LIFEOSV2_USER_GUIDE.md) | Daily operation |
| [Technical Documentation](docs/LIFEOSV2_TECHNICAL_DOCS.md) | Architecture, deploy, engines |
| [Cmd grammar](docs/LIFEOSV2_CMD_GRAMMAR.md) | Capture / go / do tokens |
| [Fragment inventory](docs/LIFEOSV2_FRAGMENT_INVENTORY.md) | Template ↔ endpoint map |
| [Backlog](docs/LIFEOSV2_BACKLOG.md) | Phase status |
| [Defects](docs/LIFEOSV2_DEFECTS.md) | Known issues |
| [Seed catalog](docs/SEED_DATA.md) | `seed_data` coverage |
| [AGENTS.md](AGENTS.md) | Agent / engineering rules |

---

## Quick start

```powershell
python validate_sandbox.py
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py create_owner --username owner --password "your-password"
python manage.py seed_data
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

Optional: set `DATABASE_URL` in `.env` for Postgres. Google/Microsoft OAuth clients can be entered in Settings → Calendars (preferred over env).

---

## Tests

```powershell
python manage.py test lifeos_app.tests -v 1
```

---

## Background jobs (P5-04 Celery Beat)

**Preferred** (Redis + worker with embedded Beat):

```powershell
# Redis listening on 6379, then:
celery -A lifeos_django worker -B -l info
```

Schedule: reminders every **2 min**, telemetry cache warm every **15 min**, stability daily **12:05 UTC**.

**Fallback** without Redis (cron / Task Scheduler):

```powershell
python manage.py sweep_reminders
python manage.py run_beat_jobs              # reminders + telemetry once
python manage.py run_beat_jobs --stability  # include stability
python manage.py sync_calendar
python manage.py compute_stability
```
