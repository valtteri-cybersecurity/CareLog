#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PG_DB_NAME="carelog"
DB_USER="carelog_app"
MIGRATION_USER="carelog_migrator"
PYTHON=".venv/bin/python"

fail() {
    echo "Error: $1" >&2
    exit 1
}

# The PostgreSQL server, the carelog database and the carelog_app and
# carelog_migrator accounts are created by the administrator beforehand,
# for example in a Docker container. See README.md.

check_system_postgres() {
    if [ "$EUID" -eq 0 ]; then
        fail "Run as a regular user: bash install.sh"
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        fail "python3 is required"
    fi
    if [ ! -f requirements.txt ] || [ ! -f carelog/database/postgres_migrate.py ]; then
        fail "Required CareLog files are missing"
    fi
    if [ -L .env ] || [ -L .venv ]; then
        fail ".env and .venv must not be symbolic links"
    fi
    if [ ! -f .env ]; then
        fail ".env with the CARELOG_PG_* settings is required"
    fi
    if [ ! -O .env ]; then
        fail ".env must be owned by the current user"
    fi
    if [ -e .venv ] && [ ! -O .venv ]; then
        fail ".venv must be owned by the current user"
    fi
    if command -v git >/dev/null 2>&1; then
        if git ls-files --error-unmatch .env >/dev/null 2>&1; then
            fail ".env is tracked by Git; remove it from version control first"
        fi
    fi
}

prepare_postgres_config() {
    chmod 600 .env
    "$PYTHON" - "$PG_DB_NAME" "$DB_USER" <<'PYTHON'
import sys

from carelog.database.postgres_connection import load_postgres_config

database, user = sys.argv[1:]
config = load_postgres_config()
if config["CARELOG_PG_HOST"] not in ("127.0.0.1", "localhost"):
    raise SystemExit("Invalid CARELOG_PG_HOST in .env")
if config["CARELOG_PG_DATABASE"] != database or config["CARELOG_PG_USER"] != user:
    raise SystemExit("Invalid PostgreSQL database or application user in .env")
PYTHON
}

validate_postgres_app_connection() {
    "$PYTHON" - "$DB_USER" "$PG_DB_NAME" <<'PYTHON'
import sys

from carelog.database.postgres_connection import get_postgres_connection

user, database = sys.argv[1:]
with get_postgres_connection() as connection, connection.cursor() as cursor:
    cursor.execute("SELECT current_user, current_database()")
    if cursor.fetchone() != (user, database):
        raise SystemExit("Connection does not use the expected application account")
PYTHON
}

run_postgres_migrations() {
    local migration_password
    # The migration password is asked every time and never saved to a file.
    read -r -s -p "Password for $MIGRATION_USER: " migration_password
    echo
    if [ -z "$migration_password" ]; then
        fail "The password for $MIGRATION_USER is required"
    fi

    # The migration account owns the tables. After the migrations it
    # resets the privileges of carelog_app and checks that nothing extra
    # remains.
    echo "Running PostgreSQL migrations with the migration account..."
    printf '%s\n' "$migration_password" | "$PYTHON" -c '
import sys

from carelog.database.postgres_migrate import run_postgres_migrations
from carelog.database.postgres_permissions import apply_app_permissions

app_user = sys.argv[1]
password = sys.stdin.readline().rstrip("\n")
run_postgres_migrations(password=password)
apply_app_permissions(app_user, password=password)
' "$DB_USER"
    unset migration_password
}

install_python() {
    if [ ! -f "$PYTHON" ]; then
        python3 -m venv .venv
    fi
    "$PYTHON" -m pip install -r requirements.txt
}

main() {
    check_system_postgres
    install_python
    prepare_postgres_config
    validate_postgres_app_connection
    run_postgres_migrations
    echo "CareLog installation completed successfully."
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if [ "$#" -ne 0 ]; then
        fail "Usage: bash install.sh"
    fi
    main
fi
