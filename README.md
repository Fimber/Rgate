# ReGate

A multi-tenant results system for Nigerian private schools. A teacher enters scores on a phone. The class teacher and head of school approve. Parents open a branded result. The bursar can hold a debtor. The record stays.

This is the MVP: results, not a school management system.

## What it does

- School onboarding wizard, Nigerian defaults, copy-last-session
- Students, staff, enrollments per session and term
- Mobile score entry with offline drafts and Excel round-trip
- Server-side computation: totals, grades, ties, class positions, session average
- Workflow: Draft → Submitted → Reviewed → Approved → Published → Archived
- Result cards (HTML + PDF) in three designs — Classic, Compact, Colour band — with an option to leave positions off; broadsheet, transcript
  (example photos live in `static/img/report-cards/`; regenerate with `python manage.py render_card_examples`)
- Parent accounts, student accounts, scratch-card PINs
- Fee-status gating (cleared / part / owing) with logged overrides
- SMS hook (console provider in development)
- Platform HQ: schools, usage, impersonation, audit log

## Decisions taken for launch

1. **Both account login and result PINs** ship together. The school chooses the mix.
2. **Assessment components are not hardcoded.** Each school sets its own maxima and the total can be anything; grades, averages and the pass mark use the percentage of that total.
3. **Nursery and creche use skill checklists**, not numeric scores. Primary and secondary use scored cards.
4. **Publication-night parent login support is the school's first line.** ReGate owns the platform.
5. **If a school leaves:** read-only access, full export on request, 90-day deletion notice.

## Run it locally

You need Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000/

Settings are secure by default: without `.env` the app runs with `DEBUG=false` and refuses to start
without a real `SECRET_KEY`. The `.env.example` you copied turns on debug for local work.

## Demo school — Greenfield College, Port Harcourt

| Who | Phone | Password |
|---|---|---|
| Platform HQ | 08000000000 | admin1234 |
| School admin | 08011111111 | school1234 |
| Head of school | 08022222222 | head1234 |
| Class teacher | 08033333333 | teacher1234 |
| Subject teacher | 08044444444 | teacher1234 |
| Parent (Adaeze + Precious) | 08055555501 | parent1234 |
| Student (Adaeze) | 08066666666 | student1234 |

PIN path: admission `GFC/001` + PIN `DEMO1234` at `/portal/pin/`

Fee hold demo: **GFC/008 Tamarabrakemi George** is owing. Clear her on `/app/` → Fee status and the parent can open the result immediately.

JSS 1 A is already scored, approved and published so you can walk the parent path in under a minute.

## Architecture

- Django, server-rendered HTML, one CSS file, no SPA
- SQLite for local use; set `DB_*` for PostgreSQL in production
- `school_id` on tenant tables, request scoped by subdomain or login
- Computed values stored on the result sheet at publish time
- Every score hangs off an **enrollment**, never directly off a student
- SMS and PDF sit behind services so providers can be swapped

Production notes from the spec still apply: queue PDF and SMS, freeze deploys at term end, load-test publication Friday, encrypt backups, name the school as controller and ReGate as processor in the contract.

## Security model

- **Tenant isolation.** Every view that takes an id scopes it to `request.school`; a teacher's
  score endpoints also check the subject is assigned to them. `tests/test_security.py` runs
  two schools side by side and tries to cross between them.
- **Roles.** Fees, PINs, students, settings, structure and setup are admin / head of school
  only. Class review needs the class-teacher assignment; approval needs head of school.
- **Credentials.** No default passwords for real users: new staff, school admins and imported
  parents get random temporary passwords and must change them at first sign-in. Parents get
  theirs by SMS; the SMS log masks it. Passwords are checked against common-password and
  similarity rules.
- **Brute force.** Login is limited per IP+account and per account; PINs per IP and per
  admission number. PINs are 10 characters from an unambiguous alphabet. Use Redis or
  Memcached (`CACHE_BACKEND`) when you run more than one worker.
- **Audit.** Fee changes, overrides, PIN batches, staff creation, exports, school suspension
  and impersonation start/stop are written to the audit log.
- **Uploads.** Images are checked with Pillow (type and 2 MB); spreadsheets are capped at 5 MB
  and parse errors become messages, not 500s.

## Production

```bash
docker build -t regate .
docker run --env-file .env -p 8000:8000 regate
```

The image runs migrations, then gunicorn, and exposes `/healthz/` for the load balancer.
Set `DEBUG=false`, a real `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, PostgreSQL
(`DB_*`) and, behind a TLS proxy, `BEHIND_TLS_PROXY=true`. HTTPS redirect, secure cookies and
HSTS switch on automatically when debug is off; `python manage.py check --deploy` should be clean.

`/media/` is not served by Django in production. Serve logos and photos from your web server
or object storage; result PDFs are always served through the permission-checked
`/portal/result/<id>/pdf/` view.

## Tests

```bash
python manage.py test                 # whole suite, ~5 s
coverage run manage.py test && coverage report
ruff check . && ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs lint, tests on SQLite and PostgreSQL, a migrations check
and `check --deploy` on every push.
