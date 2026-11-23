# CareLog

**CareLog** is a Python and PostgreSQL application for managing the daily work of a small home assistance business: clients, services, visits, mileage, expenses and reports.

> **Project status:** Under development. The database, installer and the client and service logic are in place. The API, authentication and user interface are not built yet, so the application is not ready for production use or for real clients' personal data.

## Current Status

| Area | Status |
| --- | --- |
| PostgreSQL 16 schema and versioned migrations (v001–v011) | Implemented |
| MySQL schema and migrations (v001–v011) | Legacy, kept during the transition |
| Installer with least-privilege database accounts | Implemented |
| Clients: add, get, list, update, archive | Implemented and tested |
| Services: add, get, list, update | Implemented and tested |
| Trips (client-specific routes and mileage) | Next |
| Visits, notes and expenses | Planned |
| Authentication and authorization | Planned |
| FastAPI layer | Planned |
| Finnish browser user interface | Planned |
| Reports and receipt management | Planned |

## Technology Stack

- Python 3, Psycopg 3, python-dotenv
- PostgreSQL 16 (Docker)
- MySQL 8 and PyMySQL (legacy installation, kept during the transition)
- pytest
- Bash (installer)
- Planned: FastAPI, HTML, CSS and JavaScript

## Installation

### PostgreSQL (current)

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
```

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
bash install.sh --postgres
source .venv/bin/activate
```

The installer creates the virtual environment, checks `.env` and the `carelog_app` connection, asks for the `carelog_migrator` password (it is not saved anywhere), runs pending migrations as `carelog_migrator` and gives `carelog_app` only the table privileges it needs. It stops if `carelog_app` still has extra privileges, for example ownership, `CREATE` on the schema or privileges granted by another account.

### MySQL (legacy)

The original MySQL installation still works during the transition. It requires Ubuntu or Linux Mint (`apt-get`, `systemd`), `sudo` access and a local MySQL server that the installer can manage through `sudo mysql`.

```bash
bash install.sh
```

It creates the `CareLog` database if it is missing, runs the MySQL migrations with a temporary `carelog_migrator` account and generates the `CARELOG_*` settings in `.env`. Review `install.sh` before running it on a machine that already has MySQL data. The application services use PostgreSQL; the MySQL code is kept until its removal is approved.

`.env` and `.venv/` are excluded from Git. Never commit passwords or other secrets.

## Running Tests

```bash
source .venv/bin/activate
python -m pytest -v -rs --ignore=tests/test_install_permissions.py
```

Database tests are skipped unless their test environment variables are set, so a green run does not mean that every test ran. Check the skipped count in the summary.

### PostgreSQL tests

The PostgreSQL tests create a temporary `carelog_test_*` database for every test and drop it afterwards. The permission tests also create and drop temporary login accounts. Run them only against a separate, disposable server, never against `carelog-postgres`:

```bash
docker run --rm -d --name carelog-postgres-test -p 127.0.0.1:5434:5432 -e POSTGRES_PASSWORD=carelog-test-only --tmpfs /var/lib/postgresql/data postgres:16
```

```bash
export CARELOG_TEST_PG_PORT=5434 CARELOG_TEST_PG_USER=postgres CARELOG_TEST_PG_PASSWORD=carelog-test-only
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

### MySQL tests (legacy migrations)

The MySQL migration tests (`tests/test_migrate.py`, `tests/test_v*.py`) need a separate MySQL test account. Never use `carelog_app` for testing; the test fixture refuses it.

| Variable | Description |
| --- | --- |
| `CARELOG_TEST_MYSQL_USER` | Test user, limited to databases named `carelog_test_*` |
| `CARELOG_TEST_MYSQL_PASSWORD` | Test user password |
| `CARELOG_TEST_MYSQL_HOST` | Server address (default `127.0.0.1`) |
| `CARELOG_TEST_MYSQL_PORT` | Port (default `3306`) |
| `CARELOG_TEST_MYSQL_SOCKET` | Optional socket |

The installer permission tests (`tests/test_install_permissions.py`) create and drop databases, users and roles and change global MySQL settings, so they must only be run against an isolated MySQL test server.

## Security

- The application connects as `carelog_app`, which has table-level privileges only. It cannot change the database structure, read password hashes, delete clients, services or visits, or change migration history.
- PostgreSQL: migrations run as `carelog_migrator`, which owns the tables. `carelog/database/postgres_permissions.py` is the source of truth for the `carelog_app` privileges and checks that no extra privileges remain.
- MySQL (legacy): migrations run under a temporary `carelog_migrator` account that is removed afterwards. `install.sh` (`grant_app_permissions()`) holds the privileges and refuses broader grants, such as `CareLog.*`.
- All SQL queries are parameterized.
- Do not use real client data in development or tests.

## Project Structure

```text
CareLog/
├── carelog/
│   ├── database/
│   │   ├── postgres_connection.py   # PostgreSQL connections
│   │   ├── postgres_migrate.py      # PostgreSQL migration runner
│   │   ├── postgres_migrations/     # PostgreSQL v001–v011
│   │   ├── postgres_permissions.py  # carelog_app privileges
│   │   ├── connection.py            # MySQL connections (legacy)
│   │   ├── migrate.py               # MySQL migration runner (legacy)
│   │   ├── migrations/              # MySQL v001–v011 (legacy)
│   │   └── repositories/            # parameterized SQL queries
│   └── services/              # validation and business logic
├── tests/                     # pytest tests
├── docs/                      # planning documents, UI sketches, Aurora DSQL notes
├── install.sh
└── requirements.txt
```

The service layer validates input and calls the repository layer, which runs the SQL queries.

## Roadmap

1. Trips: client-specific default routes and mileage
2. Visits, visit notes and expenses
3. Authentication and authorization (admin and worker roles)
4. FastAPI layer
5. Finnish browser user interface
6. Reports and receipt management

---

**Repository:** [valtteri-cybersecurity/CareLog](https://github.com/valtteri-cybersecurity/CareLog)
