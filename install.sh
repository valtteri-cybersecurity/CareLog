#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

DB_NAME="CareLog"
DB_USER="carelog_app"
MIGRATION_USER="carelog_migrator"
PYTHON=".venv/bin/python"
MIGRATION_USER_CREATED=0

fail() {
    echo "Error: $1" >&2
    exit 1
}

mysql_admin() {
    sudo mysql --no-defaults --protocol=socket --user=root "$@"
}

drop_migration_user() {
    if [ "$MIGRATION_USER_CREATED" -eq 1 ]; then
        if ! mysql_admin -e "DROP USER '$MIGRATION_USER'@'localhost'"; then
            return 1
        fi
        MIGRATION_USER_CREATED=0
    fi
}

cleanup() {
    status=$?
    trap - EXIT
    if ! drop_migration_user; then
        echo "CRITICAL: Could not remove carelog_migrator. Remove it manually." >&2
        status=1
    fi
    exit "$status"
}

check_system() {
    if [ "$EUID" -eq 0 ]; then
        fail "Run as a regular user: bash install.sh"
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        fail "sudo is required"
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        fail "Ubuntu or Linux Mint is required"
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        fail "systemd is required"
    fi
    if [ ! -f requirements.txt ] || [ ! -f carelog/database/migrate.py ]; then
        fail "Required CareLog files are missing"
    fi
    if [ -L .env ] || [ -L .venv ]; then
        fail ".env and .venv must not be symbolic links"
    fi
    if [ -e .env ] && [ ! -f .env ]; then
        fail ".env must be a regular file"
    fi
    if [ -f .env ] && [ ! -O .env ]; then
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
    sudo -v
}

install_packages() {
    echo "Installing system dependencies..."
    sudo apt-get update
    sudo apt-get install -y mysql-server python3 python3-venv python3-pip openssl
    sudo systemctl enable --now mysql
    mysql_admin -e "SELECT 1" >/dev/null
}

install_python() {
    if [ ! -f "$PYTHON" ]; then
        python3 -m venv .venv
    fi
    "$PYTHON" -m pip install -r requirements.txt
}

prepare_database() {
    if [ ! -f .env ]; then
        database_count="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = '$DB_NAME'")"
        user_count="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM mysql.user WHERE user = '$DB_USER' AND host = 'localhost'")"
        if [ "$database_count" -ne 0 ] || [ "$user_count" -ne 0 ]; then
            fail "Database or application user exists without .env. Manual review required"
        fi

        app_password="Aa1!$(openssl rand -hex 32)"
        mysql_admin <<SQL
CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '$DB_USER'@'localhost' IDENTIFIED BY '$app_password';
SQL
        cat > .env <<EOF
CARELOG_HOST=localhost
CARELOG_DATABASE=$DB_NAME
CARELOG_USER=$DB_USER
CARELOG_PASSWORD=$app_password
EOF
        unset app_password
        echo "Database and application account created."
    fi

    chmod 600 .env
    "$PYTHON" - "$DB_NAME" "$DB_USER" <<'PYTHON'
import sys

from carelog.database.connection import get_connection, load_config

database, user = sys.argv[1:]
config = load_config()
if config["CARELOG_HOST"] != "localhost":
    raise SystemExit("Invalid CARELOG_HOST in .env")
if config["CARELOG_DATABASE"] != database or config["CARELOG_USER"] != user:
    raise SystemExit("Invalid database or application user in .env")

with get_connection(database="") as connection, connection.cursor() as cursor:
    cursor.execute("SELECT CURRENT_USER()")
    if cursor.fetchone()[0] != user + "@localhost":
        raise SystemExit("Connection does not use the expected local application account")
PYTHON
}

check_schema() {
    table_count="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$DB_NAME'")"
    history_count="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$DB_NAME' AND table_name = 'schema_migrations'")"
    if [ "$table_count" -gt 0 ] && [ "$history_count" -eq 0 ]; then
        fail "Existing database has tables without migration history. Manual review required"
    fi
}

check_app_permissions() {
    local grants grant account locked
    account="\`$DB_USER\`@\`localhost\`"
    grants="$(mysql_admin -N -s -e "SHOW GRANTS FOR '$DB_USER'@'localhost'")"
    while IFS= read -r grant; do
        case "$grant" in
            "GRANT USAGE ON *.* TO $account") ;;
            "GRANT "*" ON \`$DB_NAME\`."*" TO $account") ;;
            "GRANT "*" ON \`$DB_NAME\`."*" TO $account WITH GRANT OPTION") ;;
            *) fail "Application account has global, role or other unexpected grants. Manual review required" ;;
        esac
    done <<< "$grants"

    locked="$(mysql_admin -N -s -e "SELECT account_locked FROM mysql.user WHERE User = '$DB_USER' AND Host = 'localhost'")"
    if [ "$locked" != "N" ]; then
        fail "Application account is locked or missing. Manual review required"
    fi
}

reset_app_permissions() {
    mysql_admin -e "ALTER USER '$DB_USER'@'localhost' ACCOUNT LOCK"
    local sessions
    sessions="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM information_schema.processlist WHERE USER = '$DB_USER'")"
    if [ "$sessions" -ne 0 ]; then
        mysql_admin -e "ALTER USER '$DB_USER'@'localhost' ACCOUNT UNLOCK"
        fail "Stop the application and close its database sessions before retrying"
    fi

    mysql_admin -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '$DB_USER'@'localhost'"
}

grant_app_permissions() {
    mysql_admin <<SQL
GRANT SELECT (id, email, display_name, role, is_active) ON \`$DB_NAME\`.users TO '$DB_USER'@'localhost';
GRANT SELECT, INSERT, UPDATE ON \`$DB_NAME\`.clients TO '$DB_USER'@'localhost';
GRANT SELECT ON \`$DB_NAME\`.services TO '$DB_USER'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`$DB_NAME\`.trips TO '$DB_USER'@'localhost';
GRANT SELECT, INSERT, UPDATE ON \`$DB_NAME\`.visits TO '$DB_USER'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`$DB_NAME\`.visit_notes TO '$DB_USER'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`$DB_NAME\`.expenses TO '$DB_USER'@'localhost';
ALTER USER '$DB_USER'@'localhost' ACCOUNT UNLOCK;
SQL
}

check_migration_user() {
    local existing_count mandatory_roles
    mandatory_roles="$(mysql_admin -N -s -e 'SELECT @@GLOBAL.mandatory_roles')"
    if [ -n "$mandatory_roles" ]; then
        fail "MySQL has mandatory roles. Review effective privileges before using this installer"
    fi

    existing_count="$(mysql_admin -N -s -e "SELECT COUNT(*) FROM mysql.user WHERE User = '$MIGRATION_USER' AND Host = 'localhost'")"
    if [ "$existing_count" -ne 0 ]; then
        fail "Migration account already exists. Inspect and remove it manually"
    fi
}

run_migrations() {
    local credentials migration_password
    credentials="$(mysql_admin -N -B -r -e "CREATE USER '$MIGRATION_USER'@'localhost' IDENTIFIED BY RANDOM PASSWORD")"
    MIGRATION_USER_CREATED=1
    migration_password="$(cut -f3 <<< "$credentials")"
    unset credentials
    if [ "${#migration_password}" -lt 20 ]; then
        fail "MySQL did not generate a migration password of at least 20 characters"
    fi
    mysql_admin -e "GRANT SELECT, INSERT, CREATE, ALTER, REFERENCES ON \`$DB_NAME\`.* TO '$MIGRATION_USER'@'localhost'"

    reset_app_permissions
    echo "Running database migrations with the dedicated migration account..."
    printf '%s\n' "$migration_password" | "$PYTHON" -c '
import sys
from carelog.database.migrate import run_migrations

password = sys.stdin.readline().rstrip("\n")
run_migrations(password=password)
'
    unset migration_password
    drop_migration_user
    grant_app_permissions
}

main() {
    check_system
    install_packages
    install_python
    check_migration_user
    prepare_database
    check_schema
    check_app_permissions
    run_migrations
    echo "CareLog installation completed successfully."
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    main
fi
