# CareLog

**CareLog** is a Python and MySQL application under development for planning and recording the daily work of a small home assistance or errand assistance business. Its goal is to simplify the management of client visits, working hours, mileage, expenses, and reports.

> **Project status:** Under development. The database foundation and installation tools have been implemented, but the client management service layer, FastAPI interface, authentication, and user interface are still being developed. The application is not ready for production use or for storing real clients' sensitive information.

## Features and Development Status

| Component | Status |
| --- | --- |
| Core MySQL database schema | Implemented |
| Versioned migrations v001–v008 | Implemented |
| Database schema and integrity checks | Implemented |
| Installation script and separate database accounts | Implemented |
| Migration tests (pytest) | **32 passed** in the latest reported local run (November 19, 2026) |
| Installer permission tests (pytest) | Implemented; require a separate, isolated MySQL test server |
| Adding, retrieving, listing, updating, and archiving clients | Planned |
| Service layer and business rules | Planned |
| Weekly visit planning and visit logging | Planned |
| Reporting and CSV export | Planned |
| FastAPI, authentication, and browser-based user interface | Planned |

## Technologies

- **Python 3** – application logic and database operations
- **MySQL** – data storage, foreign keys, and `CHECK` constraints
- **PyMySQL** – MySQL connections from Python
- **python-dotenv** – reading database connection settings from `.env`
- **pytest** – automated tests
- **Bash** – installation automation

The current installation script targets **Ubuntu and Linux Mint** environments that use `apt-get` for package management, `systemd` for service management, and `sudo` for administrative access.

## Development Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/valtteri-cybersecurity/CareLog.git
cd CareLog
```

### 2. Run the Installer

```bash
bash install.sh
```

The installation script:

1. Checks the required system tools and installs dependencies.
2. Creates the Python virtual environment in `.venv/` and installs packages from `requirements.txt`.
3. Creates the local `CareLog` database and `carelog_app` account if necessary.
4. Creates the `.env` configuration file if it does not already exist.
5. Creates a temporary `carelog_migrator` account and applies any pending migrations.
6. Removes the migration account and assigns table-level privileges to the application account.

The installation requires administrative access to the local MySQL server through `sudo mysql`. **Review `install.sh` before running it**, especially if the machine already contains MySQL databases or a CareLog installation. The script does not automatically overwrite an existing installation whose state cannot be verified.

### 3. Activate the Virtual Environment

```bash
source .venv/bin/activate
```

The current installation prepares the database foundation. It **does not start a completed web application**, because the API and user interface are still under development.

### Database Configuration

The installer creates an `.env` file in the project root using the following settings:

```dotenv
CARELOG_HOST=localhost
CARELOG_DATABASE=CareLog
CARELOG_USER=carelog_app
CARELOG_PASSWORD=<password-generated-by-installer>
```

The example above is not a ready-to-use configuration file: the installer generates the actual password automatically. Never commit database passwords to GitHub, source code, or documentation.

`.env` and `.venv/` are excluded from version control through `.gitignore`. The installer sets the `.env` file permissions to `600`.

## Project Structure

```text
CareLog/
├── carelog/
│   ├── __init__.py
│   └── database/
│       ├── __init__.py
│       ├── connection.py
│       ├── migrate.py
│       └── migrations/
│           ├── v001_users.py
│           ├── v002_clients.py
│           ├── v003_services.py
│           ├── v004_trips.py
│           ├── v005_visits.py
│           ├── v006_visit_notes.py
│           ├── v007_expenses.py
│           └── v008_business_constraints.py
├── tests/
│   ├── conftest.py
│   ├── migration_helpers.py
│   ├── test_migrate.py
│   ├── test_install_permissions.py
│   └── test_v*.py
├── docs/
├── install.sh
├── requirements.txt
└── README.md
```

### Database Tables

| Table | Purpose |
| --- | --- |
| `users` | Application users and roles |
| `clients` | Client contact information and archiving |
| `services` | Services, descriptions, and default hourly rates |
| `trips` | Client-specific predefined routes and distances |
| `visits` | Planned and completed client visits |
| `visit_notes` | Notes associated with individual visits |
| `expenses` | Visit-related and other business expenses |
| `schema_migrations` | Applied database migration versions |

Migrations **v001–v007** create the core tables. **V008** adds business-related `CHECK` constraints for values such as mileage, prices, expense amounts, and visit times.

`carelog/database/connection.py` defines a consistent SQL mode and UTC session timezone for database connections. `carelog/database/migrate.py` runs and validates database migrations, including the definitions and enforcement of the v008 `CHECK` constraints. Its constraint validation handles MySQL formatting differences, including escaped empty-string literals.

## Testing

First, activate the virtual environment:

```bash
source .venv/bin/activate
```

Run the tests:

```bash
python -m pytest -v -rs
```

**Note:** MySQL tests require a dedicated test server and environment variables. Without these settings, some tests are skipped (`SKIPPED`), so a successful pytest run does not necessarily mean that all integration tests have passed.

### MySQL Integration Tests

The following test environment variables are supported:

| Variable | Description |
| --- | --- |
| `CARELOG_TEST_MYSQL_USER` | MySQL test user |
| `CARELOG_TEST_MYSQL_PASSWORD` | Test user password |
| `CARELOG_TEST_MYSQL_HOST` | Test server address (default: `127.0.0.1`) |
| `CARELOG_TEST_MYSQL_PORT` | MySQL port (default: `3306`) |
| `CARELOG_TEST_MYSQL_SOCKET` | Optional MySQL socket |

Run the migration suite with:

```bash
python -m pytest -v tests/test_migrate.py tests/test_v*.py -rs --tb=short
```

**Latest reported local result (November 19, 2026): 32 passed, 0 failed, 0 skipped.** This result covers the migration runner and migration tests for v001–v008, including v008 business constraints. It was reported after fixing the validation of MySQL's escaped empty-string representation in `chk_notes_content`.

This is a **local test result, not a CI status**. It does not include `tests/test_install_permissions.py` or establish that the entire application is production-ready.

The migration test fixture creates temporary test databases and removes them after testing. The test user must therefore have the necessary permissions **only on a dedicated test environment**.

### Installer Permission Tests

`tests/test_install_permissions.py` additionally requires:

- `CARELOG_TEST_INSTALLER=1`
- `CARELOG_TEST_MYSQL_SOCKET` – the socket of the dedicated MySQL test server
- `CARELOG_TEST_MYSQL_SERVER_UUID` – the previously verified UUID of that server

```bash
python -m pytest -v tests/test_install_permissions.py -rs
```

> **WARNING:** Do not run installer permission tests against a production MySQL server or a regular development server containing data that must be preserved. These tests create and delete databases, users, and roles. One test temporarily modifies MySQL's global `mandatory_roles` setting. Use an isolated MySQL test server dedicated to this purpose.

## Planned Application Architecture

Future development will separate three responsibilities:

1. **API layer (FastAPI):** receives HTTP requests and handles authentication and request processing.
2. **Service layer (`services/`):** validates input and implements business rules.
3. **Repository layer (`database/repositories/`):** executes parameterized SQL queries and returns database results.

These layers are **planned**; the current repository primarily contains the database and installation foundation.

### Next Development Task: Client Management

Client management will be implemented in the following order:

1. `add_client()` – add a client
2. `get_client()` – retrieve client details
3. `list_clients()` – list clients
4. `update_client()` – update client details
5. `archive_client()` – archive a client without deleting historical records

The first goal is to design, implement, and test `add_client()` before moving on to the remaining functions.

## Security and Privacy

- The `carelog_app` account has restricted table-level and column-level privileges.
- Database migrations run under a separate, temporary `carelog_migrator` account.
- The database schema uses foreign keys and `CHECK` constraints.
- Passwords stored in `.env` must never be committed to the repository.
- Sensitive client information and health data must not be used as development or test data.
- Authentication, authorization checks, data retention and deletion policies, backups, and recovery testing must be completed **before production use**.

## Development Principles

- Plan each function's responsibilities, inputs, and error cases before implementation.
- Keep Python code clear, simple, and consistent.
- Use parameters in SQL queries; never interpolate user-provided values directly into SQL statements.
- Add automated tests for new features.
- Preserve migration history integrity and test both fresh installations and upgrade paths.

---

**Repository:** [valtteri-cybersecurity/CareLog](https://github.com/valtteri-cybersecurity/CareLog)
