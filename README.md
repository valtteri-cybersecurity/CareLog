# CareLog

**CareLog** is a Python and PostgreSQL application for managing the daily work of a small home assistance business: clients, services, visits, mileage, expenses and reports.

> **Project status:** Under development. The database, installer and the service layer for the core records are in place. The API, authentication and user interface are not built yet, so the application is not ready for production use or for real clients' personal data.

## Current Status

| Area | Status |
| --- | --- |
| PostgreSQL 16 schema and versioned migrations (v001–v014) | Implemented |
| User tracking (v014): worker, creator and latest editor of records | Implemented in every service (`actor_user_id`) |
| Installer with least-privilege database accounts | Implemented |
| Clients: add, get, list, update, archive | Implemented and tested |
| Services: add, get, list, update | Implemented and tested |
| Client-specific trips (saved routes and mileage) | Implemented and tested |
| Visits: planned and completed visits, weekly planning | Implemented and tested; a worker handles only their own visits, an admin every worker's |
| Visit notes with edit history | Implemented and tested |
| Expenses | Implemented and tested |
| Visit trip legs (multi-stop trips of a visit) | Implemented and tested |
| User check and worker ownership check (`carelog/services/user_validation.py`) | Used by every service |
| Authentication | Not started; `actor_user_id` is trusted internal input until then |
| FastAPI layer | Not started |
| Finnish browser user interface | Not started |
| Reports and receipt storage | Not started |

## Technology Stack

- Python 3, Psycopg 3, python-dotenv
- PostgreSQL 16 (Docker)
- pytest
- Bash (installer)
- Planned: FastAPI, HTML, CSS and JavaScript

## Installation

**Prerequisites:** Python 3 with `venv`, and a PostgreSQL 16 server that listens only on the local machine, for example the Docker container `carelog-postgres` on `127.0.0.1:5433`.

The administrator creates the database and the two accounts once. Use long random passwords and never commit them:

```sql
-- As the PostgreSQL administrator, for example: docker exec -it carelog-postgres psql -U postgres
CREATE ROLE carelog_migrator LOGIN PASSWORD '<random password>';
CREATE ROLE carelog_app LOGIN PASSWORD '<random password>';
CREATE DATABASE carelog;
REVOKE ALL ON DATABASE carelog FROM PUBLIC;
GRANT CONNECT ON DATABASE carelog TO carelog_migrator, carelog_app;
\connect carelog
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO carelog_migrator;
GRANT USAGE ON SCHEMA public TO carelog_app;
```

- `CONNECT`: both accounts may connect to `carelog`; other accounts may not.
- `USAGE` and `CREATE` on `public`: `carelog_migrator` creates and owns all tables, so only it can change the structure.
- `USAGE` only on `public`: `carelog_app` can use the tables it is granted, but cannot create database objects.

The application settings are in `.env` (mode `600`, never committed):

```text
CARELOG_PG_HOST=127.0.0.1
CARELOG_PG_PORT=5433
CARELOG_PG_DATABASE=carelog
CARELOG_PG_USER=carelog_app
CARELOG_PG_PASSWORD=<carelog_app password>
```

Then run:

```bash
bash install.sh
source .venv/bin/activate
```

The installer creates the virtual environment, checks `.env` and the `carelog_app` connection, asks for the `carelog_migrator` password (it is not saved anywhere), runs pending migrations as `carelog_migrator` and gives `carelog_app` only the table privileges it needs. It stops if `carelog_app` still has extra privileges, for example ownership, `CREATE` on the schema or privileges granted by another account.

`.env` and `.venv/` are excluded from Git. Never commit passwords or other secrets.

## Running Tests

```bash
source .venv/bin/activate
python -m pytest -v -rs
```

Database tests are skipped unless the test environment variables below are set, so a green run does not mean that every test ran. Check the skipped count in the summary.

The database tests create a temporary `carelog_test_*` database for every test and drop it afterwards. Service and permission tests copy a template database that is migrated to the newest version once per test run (fixture `migrated_cursor`) and use the shared test users admin, worker, other_worker and inactive (fixture `user_ids`); only the migration tests build older schema versions themselves. The permission tests also create and drop temporary login accounts. Run them only against a separate, disposable server, never against `carelog-postgres`. Start one with its data in memory:

```bash
docker run --rm -d --name carelog-postgres-test -p 127.0.0.1:5434:5432 -e POSTGRES_PASSWORD=carelog-test-only --tmpfs /var/lib/postgresql/data postgres:16
```

Mark it as disposable. The tests stop at once if this mark is missing, or if the server has the `carelog` database or the `carelog_app` or `carelog_migrator` account:

```bash
docker exec carelog-postgres-test psql -U postgres -c "COMMENT ON DATABASE postgres IS 'carelog-disposable-test-server'"
```

```bash
export CARELOG_TEST_PG_PORT=5434 CARELOG_TEST_PG_USER=postgres CARELOG_TEST_PG_PASSWORD=carelog-test-only
```

```bash
python -m pytest -v -rs
```

```bash
docker stop carelog-postgres-test
```

| Variable | Description |
| --- | --- |
| `CARELOG_TEST_PG_USER` | Test user that can create databases and roles (not `carelog_app` or `carelog_migrator`) |
| `CARELOG_TEST_PG_PASSWORD` | Test user password |
| `CARELOG_TEST_PG_HOST` | Server address (default `127.0.0.1`) |
| `CARELOG_TEST_PG_PORT` | Port (default `5432`) |

## Users and Authorization

Migration v014 adds user tracking. Every user column references `users(id)` with `ON DELETE RESTRICT`.

| Table | User columns |
| --- | --- |
| `clients` | `created_by_user_id`, `updated_by_user_id` |
| `services`, `trips` | `created_by_user_id`, `updated_by_user_id`, `updated_at` |
| `visits` | `user_id`, `created_by_user_id`, `updated_by_user_id` |
| `visit_notes` | `created_by_user_id`, `updated_by_user_id` |
| `expenses` | `user_id`, `created_by_user_id`, `updated_by_user_id`, `updated_at` |
| `visit_trip_legs` | `created_by_user_id` |
| `visit_note_history` | `edited_by_user_id` (required since v014) |

- `actor_user_id` is the user who performs a service operation. It is the first parameter of every writing service function and of every function that reads private records. The creator (`created_by_user_id`) and the latest editor (`updated_by_user_id`) are always taken from it.
- `user_id` is the worker who owns a private record. A visit always has a worker. An expense has its own worker, which can differ from the worker of its visit, and changing the worker of a visit does not change its expenses. Kilometres (`visits.distance_km` and the trip legs) belong to the worker of the visit.
- Clients, services and saved trips are shared by the whole business and have no owner. The rules for which roles may change them are not decided yet.
- A worker sees and changes only their own visits, visit notes and their history, trip legs and expenses. Another worker's record is treated as a missing record. An admin sees and changes the records of every worker and can filter lists by worker.
- Only an admin can add a visit or an expense for another active worker, and only an admin can give a planned visit to another worker (`change_visit_worker`). The worker of a completed or cancelled visit never changes.
- The role and the active state are always read from the database (`carelog/services/user_validation.py`). An inactive user cannot use the services. Users are deactivated with `is_active`, never deleted, so their records stay.
- Every change of a note's content is saved to `visit_note_history` with its editor.

**Old development data:** v014 stops without changes if the tables already contain records, because their creator is unknown. Old rows are never deleted or linked to a user automatically. Remove the development data by hand, or start from a new, empty database, and run the installation again.

**Known limitations:** `actor_user_id` is not authenticated yet. The user check reads `users` without a row lock (the application account has no `UPDATE` on `users`), so a deactivation or role change that commits during a running write does not stop that write. Reads of shared clients, services and saved trips take no `actor_user_id`.

## Security

- The application connects as `carelog_app`, which has table-level privileges only. It cannot change the database structure, read password hashes, delete clients, services or visits, or change migration history.
- Migrations run as `carelog_migrator`, which owns the tables. `carelog/database/postgres_permissions.py` is the source of truth for the `carelog_app` privileges and checks that no extra privileges remain.
- Every change of a visit note's content is saved to `visit_note_history` by the database trigger `trg_visit_notes_history` (migrations v013 and v014), also for changes made directly in SQL. The trigger function runs as the table owner with a fixed `search_path`; `carelog_app` can only read the history.
- Since v014 every record has a required creator (`created_by_user_id`), visits and expenses a required worker (`user_id`), and the latest editor is saved in `updated_by_user_id`. All of them reference `users` with `ON DELETE RESTRICT`, so users with records are deactivated, not deleted. The trigger `trg_<table>_created_by` stops any change of `created_by_user_id`, also in direct SQL.
- The editor of a note is given by the application before each change of content, in the same transaction: `SELECT set_config('carelog.actor_user_id', '<user id>', true)`. The history trigger uses the value once and fails without it. This records the editor that the application gives; it does not authenticate the person.
- Migration v014 stops without changes if the tables already contain clients, services, visits or other records, because their creator is unknown. Old development data is never linked to a user automatically: remove it by hand or use a new, empty database.
- All SQL queries are parameterized.
- Do not use real client data in development or tests.

## Project Structure

```text
CareLog/
├── carelog/
│   ├── database/
│   │   ├── postgres_connection.py   # PostgreSQL connections
│   │   ├── postgres_migrate.py      # PostgreSQL migration runner
│   │   ├── postgres_migrations/     # PostgreSQL v001–v014
│   │   ├── postgres_permissions.py  # carelog_app privileges
│   │   └── repositories/            # parameterized SQL queries
│   └── services/              # validation and business logic
├── tests/                     # pytest tests
├── docs/                      # planning documents, UI sketches, Aurora DSQL notes
├── install.sh
└── requirements.txt
```

The service layer validates input and calls the repository layer, which runs the SQL queries.

## Roadmap

1. Authentication (Argon2 password hashing, accounts, login), with `actor_user_id` taken only from the authenticated user
2. FastAPI layer
3. Finnish browser user interface
4. Reports and receipt storage

---

**Repository:** [valtteri-cybersecurity/CareLog](https://github.com/valtteri-cybersecurity/CareLog)
