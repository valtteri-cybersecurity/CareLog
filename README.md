# CareLog

**CareLog** is a Python and MySQL application for managing the daily work of a small home assistance business: clients, services, visits, mileage, expenses and reports.

> **Project status:** Under development. The database, installer and the client and service logic are in place. The API, authentication and user interface are not built yet, so the application is not ready for production use or for real clients' personal data.

## Current Status

| Area | Status |
| --- | --- |
| MySQL schema and versioned migrations (v001–v008) | Implemented |
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

- Python 3, PyMySQL, python-dotenv
- MySQL 8
- pytest
- Bash (installer)
- Planned: FastAPI, HTML, CSS and JavaScript

## Installation

**Prerequisites:** Ubuntu or Linux Mint (`apt-get`, `systemd`), `sudo` access and a local MySQL server that the installer can manage through `sudo mysql`.

Verified environment: Linux Mint (based on Ubuntu 24.04), Python 3.12.3, MySQL 8.0.46, PyMySQL 1.2.4.

```bash
git clone https://github.com/valtteri-cybersecurity/CareLog.git
cd CareLog
bash install.sh
source .venv/bin/activate
```

The installer sets up the Python virtual environment, creates the `CareLog` database if it is missing, runs pending migrations and gives the `carelog_app` account only the privileges it needs. It generates a `.env` file (mode `600`) with the connection settings and a random password. It never replaces an existing database, and it stops if the existing installation cannot be verified. Review `install.sh` before running it on a machine that already has MySQL data.

`.env` and `.venv/` are excluded from Git. Never commit passwords or other secrets.

## Running Tests

```bash
source .venv/bin/activate
python -m pytest -v -rs
```

MySQL integration tests need a separate test account. Without the test environment variables these tests are skipped, so a green run does not mean that every test ran. Never use `carelog_app` for testing; the test fixture refuses it.

| Variable | Description |
| --- | --- |
| `CARELOG_TEST_MYSQL_USER` | Test user, limited to databases named `carelog_test_*` |
| `CARELOG_TEST_MYSQL_PASSWORD` | Test user password |
| `CARELOG_TEST_MYSQL_HOST` | Server address (default `127.0.0.1`) |
| `CARELOG_TEST_MYSQL_PORT` | Port (default `3306`) |
| `CARELOG_TEST_MYSQL_SOCKET` | Optional socket |

Latest local results (Linux Mint, November 2026):

| Test suite | Command | Result |
| --- | --- | --- |
| Clients and services | `python -m pytest -v tests/test_clients.py tests/test_services.py -rs` | 127 passed, 0 failed, 0 skipped |
| Migrations | `python -m pytest -v tests/test_migrate.py tests/test_v*.py -rs` | 32 passed, 0 failed, 0 skipped |

Total: 159 passed, 0 failed.

The installer permission tests (`tests/test_install_permissions.py`) were not part of these runs. They create and drop databases, users and roles and change global MySQL settings, so they must only be run against an isolated MySQL test server.

## Security

- The application connects as `carelog_app`, which has table-level privileges only. It cannot read password hashes, delete clients, services or visits, or change migration history.
- Migrations run under a temporary `carelog_migrator` account that is removed afterwards.
- `install.sh` is the source of truth for the privileges (`grant_app_permissions()`). It refuses to continue if the account has broader grants, such as `CareLog.*`.
- All SQL queries are parameterized.
- Do not use real client data in development or tests.

## Project Structure

```text
CareLog/
├── carelog/
│   ├── database/
│   │   ├── connection.py      # database connections
│   │   ├── migrate.py         # migration runner
│   │   ├── migrations/        # v001–v008
│   │   └── repositories/      # parameterized SQL queries
│   └── services/              # validation and business logic
├── tests/                     # pytest tests
├── docs/                      # planning documents and UI sketches
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
