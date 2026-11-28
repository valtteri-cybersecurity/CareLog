# CareLog

CareLog is a Python and PostgreSQL application for the daily work of a small home assistance business: clients, services, visits, weekly planning, mileage, visit notes and expenses.

> **Status:** under development. The database and the service layer are in place and tested. Authentication, the API and the user interface are not built yet, so CareLog is not ready for production use or real client data.

## Status

| Area | Status |
| --- | --- |
| PostgreSQL 16 schema, migrations v001–v014, least-privilege installer | Done |
| Clients, services, saved trips | Done |
| Visits and weekly planning | Done |
| Visit notes with edit history | Done |
| Expenses | Done |
| Visit trip legs (mileage) | Done |
| User tracking and admin/worker authorization in the services | Done |
| Authentication | Not started |
| FastAPI layer | Not started |
| Finnish user interface | Not started |
| Reports and receipts | Not started |

## Technology

Python 3, Psycopg 3, python-dotenv, PostgreSQL 16 (Docker), pytest, Bash and GitHub Actions. Planned: FastAPI, HTML, CSS and JavaScript.

## Installation

Requirements: Python 3 with `venv` and a local PostgreSQL 16 server, for example the Docker container `carelog-postgres` on `127.0.0.1:5433`.

Create the database and the two accounts once as the PostgreSQL administrator (`docker exec -it carelog-postgres psql -U postgres`). Use long random passwords:

```sql
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

`carelog_migrator` owns the tables and runs migrations. `carelog_app` is the application account and gets only the table privileges it needs.

Put the application settings in `.env` (mode `600`, never committed):

```text
CARELOG_PG_HOST=127.0.0.1
CARELOG_PG_PORT=5433
CARELOG_PG_DATABASE=carelog
CARELOG_PG_USER=carelog_app
CARELOG_PG_PASSWORD=<carelog_app password>
```

Then run the installer. It creates the virtual environment, asks for the `carelog_migrator` password (not saved), runs the migrations and sets the `carelog_app` privileges:

```bash
bash install.sh
```

Migration v014 stops without changes if the database already contains records, because their creator is unknown. Old rows are never deleted or linked to a user automatically: remove old development data or start from an empty database.

## Running Tests

The database tests need a separate, disposable PostgreSQL server. Never run them against `carelog-postgres`. Start one with its data in memory and mark it as disposable:

```bash
docker run --rm -d --name carelog-postgres-test -p 127.0.0.1:5434:5432 -e POSTGRES_PASSWORD=carelog-test-only --tmpfs /var/lib/postgresql/data postgres:16
```

```bash
docker exec carelog-postgres-test psql -U postgres -c "COMMENT ON DATABASE postgres IS 'carelog-disposable-test-server'"
```

Then run all tests:

```bash
source .venv/bin/activate
export CARELOG_TEST_PG_HOST=127.0.0.1 CARELOG_TEST_PG_PORT=5434 CARELOG_TEST_PG_USER=postgres CARELOG_TEST_PG_PASSWORD=carelog-test-only
python -m pytest -v -rs
```

Without `CARELOG_TEST_PG_USER` the database tests are skipped, so check that the summary shows 0 skipped. When it is set, `CARELOG_TEST_PG_HOST` and `CARELOG_TEST_PG_PORT` are required too. The tests refuse to run unless the server is marked as disposable, has no databases other than the PostgreSQL defaults and temporary `carelog_test_*` databases, and has no CareLog accounts. They also refuse the address and user of the application's own database in `.env`. During the tests every other database connection is blocked, so a unit test that forgets to mock the connection fails instead of reaching a real database. Stop the server afterwards with `docker stop carelog-postgres-test`.

Every test gets its own copy of a template database, which is migrated once per run with the same migration code as production. GitHub Actions runs the whole suite against PostgreSQL 16 on every push and pull request.

## Users and Authorization

Users have the role `admin` or `worker`. Every service function that writes data or reads private records takes `actor_user_id`, the user who performs the operation. The role and the active state are always read from the database.

- **Shared data:** clients, services and saved trips belong to the whole business. Only an admin may add clients.
- **Private records:** a visit belongs to its worker (`visits.user_id`), and so do its notes and trip legs. An expense has its own worker (`expenses.user_id`), which can differ from the worker of the visit. Mileage belongs to the worker of the visit.
- **Worker:** sees and changes only their own private records. Another worker's record looks like a missing record.
- **Admin:** sees and changes every worker's records, can add visits and expenses for other active workers, and can move a planned visit to another worker. The worker of a completed or cancelled visit never changes.
- **Authorship:** records save their creator (`created_by_user_id`, cannot be changed) and latest editor (`updated_by_user_id`). Every change of a note is saved to `visit_note_history` with its editor.
- **Inactive users** cannot use the services. Users are deactivated, never deleted, so their records stay.

## Security

- The application account cannot change the database structure, read password hashes, delete clients, services or visits, or write the note history.
- `carelog/database/postgres_permissions.py` defines the application privileges and checks that no extra privileges remain.
- Private records are filtered by worker in the SQL queries, and all queries are parameterized.
- Do not use real client data in development or tests.

**Known limitations:**

- `actor_user_id` is trusted input until authentication exists.
- A deactivation or role change that happens during a running write does not stop that write, because the application account cannot lock user rows.
- Reading shared data does not check the user yet.
- Apart from adding clients (admin only), the rules for who may change shared data are not decided yet.

## Project Structure

```text
carelog/
├── database/
│   ├── postgres_connection.py   # connections
│   ├── postgres_migrate.py      # migration runner and schema checks
│   ├── postgres_migrations/     # v001–v014
│   ├── postgres_permissions.py  # application privileges
│   └── repositories/            # parameterized SQL queries
└── services/                    # validation, business rules, user checks
tests/                           # pytest tests
docs/                            # planning documents and UI sketches
install.sh                       # installer
```

## Roadmap

1. Authentication: Argon2 password hashing, accounts and login. `actor_user_id` will come only from the signed-in user.
2. FastAPI layer
3. Finnish user interface
4. Reports and receipts

---

**Repository:** [valtteri-cybersecurity/CareLog](https://github.com/valtteri-cybersecurity/CareLog)
