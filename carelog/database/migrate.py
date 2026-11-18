from carelog.database.connection import get_connection
from carelog.database.migrations import (
    v001_users,
    v002_clients,
    v003_services,
    v004_trips,
    v005_visits,
    v006_visit_notes,
    v007_expenses,
)


# Expected column structure: name, type, nullable, default value.
# Keep these definitions consistent with the original migration files.
EXPECTED_COLUMNS = {
    "users": [
        ("id", "int", "NO", None),
        ("email", "varchar(254)", "NO", None),
        ("display_name", "varchar(150)", "NO", None),
        ("password_hash", "varchar(255)", "NO", None),
        ("role", "enum('admin','worker')", "NO", "worker"),
        ("is_active", "tinyint(1)", "NO", "1"),
        ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
    ],
    "clients": [
        ("id", "int", "NO", None),
        ("first_name", "varchar(100)", "NO", None),
        ("last_name", "varchar(100)", "NO", None),
        ("phone", "varchar(50)", "YES", None),
        ("email", "varchar(255)", "YES", None),
        ("street_address", "varchar(255)", "YES", None),
        ("postal_code", "varchar(20)", "YES", None),
        ("city", "varchar(100)", "YES", None),
        ("distance_from_home_km", "decimal(10,2)", "YES", None),
        ("archived_at", "datetime", "YES", None),
        ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
    ],
    "services": [
        ("id", "int", "NO", None),
        ("name", "varchar(150)", "NO", None),
        ("description", "text", "YES", None),
        ("default_hourly_rate", "decimal(10,2)", "YES", None),
    ],
    "trips": [
        ("id", "int", "NO", None),
        ("client_id", "int", "NO", None),
        ("start_location", "varchar(255)", "NO", None),
        ("destination", "varchar(255)", "NO", None),
        ("distance_km", "decimal(10,2)", "YES", None),
    ],
    "visits": [
        ("id", "int", "NO", None),
        ("client_id", "int", "NO", None),
        ("service_id", "int", "NO", None),
        ("status", "varchar(20)", "NO", "planned"),
        ("priority", "tinyint", "NO", "2"),
        ("planned_week", "date", "YES", None),
        ("planned_at", "datetime", "YES", None),
        ("started_at", "datetime", "YES", None),
        ("ended_at", "datetime", "YES", None),
        ("description", "text", "YES", None),
        ("distance_km", "decimal(10,2)", "YES", None),
        ("price", "decimal(10,2)", "YES", None),
        ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
    ],
    "visit_notes": [
        ("id", "int", "NO", None),
        ("visit_id", "int", "NO", None),
        ("content", "text", "NO", None),
        ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
    ],
    "expenses": [
        ("id", "int", "NO", None),
        ("visit_id", "int", "YES", None),
        ("expense_date", "date", "NO", None),
        ("amount", "decimal(10,2)", "NO", None),
        ("category", "varchar(20)", "NO", None),
        ("description", "varchar(255)", "YES", None),
    ],
}


# Foreign keys: column, referenced table, referenced column, DELETE, UPDATE.
EXPECTED_FOREIGN_KEYS = {
    "trips": [
        ("client_id", "clients", "id", "CASCADE", "RESTRICT"),
    ],
    "visits": [
        ("client_id", "clients", "id", "RESTRICT", "RESTRICT"),
        ("service_id", "services", "id", "RESTRICT", "RESTRICT"),
    ],
    "visit_notes": [
        ("visit_id", "visits", "id", "RESTRICT", "RESTRICT"),
    ],
    "expenses": [
        ("visit_id", "visits", "id", "RESTRICT", "RESTRICT"),
    ],
}


def create_migrations_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)


def get_applied_versions(cursor):
    cursor.execute("""
        SELECT version FROM schema_migrations
    """)

    results = cursor.fetchall()
    versions = set()

    for result in results:
        version = result[0]
        versions.add(version)

    return versions


def record_migration(cursor, version):
    cursor.execute("""
        INSERT INTO schema_migrations (version)
        VALUES (%s)
    """, (version,))


def table_exists(cursor, table):
    cursor.execute("""
        SELECT ENGINE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
    """, (table,))

    result = cursor.fetchone()

    if result is None:
        return False

    if result[0] != "InnoDB":
        raise RuntimeError(f"Invalid storage engine for table: {table}")

    return True


def validate_table(cursor, table):
    cursor.execute("""
        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table,))

    columns = []

    for column in cursor.fetchall():
        name, column_type, nullable, default, extra = column

        if isinstance(default, str):
            if default.lower() in ("current_timestamp", "current_timestamp()"):
                default = "CURRENT_TIMESTAMP"

        columns.append((name, column_type, nullable, default))

        extra = extra.lower().replace("default_generated", "")
        extra = extra.replace("current_timestamp()", "current_timestamp")
        extra = extra.strip()

        expected_extra = ""

        if name == "id":
            expected_extra = "auto_increment"
        elif name == "updated_at":
            expected_extra = "on update current_timestamp"

        if extra != expected_extra:
            raise RuntimeError(f"Invalid column settings: {table}.{name}")

    if columns != EXPECTED_COLUMNS[table]:
        raise RuntimeError(f"Invalid columns in table: {table}")

    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = 'PRIMARY'
        ORDER BY ORDINAL_POSITION
    """, (table,))

    primary_key = [row[0] for row in cursor.fetchall()]

    if primary_key != ["id"]:
        raise RuntimeError(f"Invalid primary key in table: {table}")

    cursor.execute("""
        SELECT COLUMN_NAME, SUB_PART
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND NON_UNIQUE = 0
          AND INDEX_NAME != 'PRIMARY'
        ORDER BY INDEX_NAME, SEQ_IN_INDEX
    """, (table,))

    unique_columns = list(cursor.fetchall())
    expected_unique_columns = []

    if table == "users":
        expected_unique_columns = [("email", None)]

    if unique_columns != expected_unique_columns:
        raise RuntimeError(f"Invalid unique constraints in table: {table}")

    cursor.execute("""
        SELECT k.COLUMN_NAME, k.REFERENCED_TABLE_SCHEMA,
               k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
               r.DELETE_RULE, r.UPDATE_RULE
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
        JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS r
          ON k.CONSTRAINT_SCHEMA = r.CONSTRAINT_SCHEMA
         AND k.CONSTRAINT_NAME = r.CONSTRAINT_NAME
         AND k.TABLE_NAME = r.TABLE_NAME
        WHERE k.TABLE_SCHEMA = DATABASE()
          AND k.TABLE_NAME = %s
          AND k.REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY k.COLUMN_NAME
    """, (table,))

    foreign_key_rows = cursor.fetchall()

    cursor.execute("SELECT DATABASE()")
    database_name = cursor.fetchone()[0]

    foreign_keys = []

    for row in foreign_key_rows:
        column, schema, reference_table, reference_column, delete_rule, update_rule = row

        if schema != database_name:
            raise RuntimeError(f"Foreign key references another database: {table}")

        if delete_rule == "NO ACTION":
            delete_rule = "RESTRICT"

        if update_rule == "NO ACTION":
            update_rule = "RESTRICT"

        foreign_key = (
            column,
            reference_table,
            reference_column,
            delete_rule,
            update_rule,
        )

        foreign_keys.append(foreign_key)

    expected_foreign_keys = EXPECTED_FOREIGN_KEYS.get(table, [])

    if foreign_keys != expected_foreign_keys:
        raise RuntimeError(f"Invalid foreign keys in table: {table}")


def run_migrations(database=None, *, password):
    if not password:
        raise ValueError("A password for carelog_migrator is required")

    connection = None
    cursor = None

    try:
        connection = get_connection(
            database=database,
            user="carelog_migrator",
            password=password,
        )

        cursor = connection.cursor()
        create_migrations_table(cursor)
        applied_versions = get_applied_versions(cursor)

        migrations = [
            (1, "users", v001_users.upgrade),
            (2, "clients", v002_clients.upgrade),
            (3, "services", v003_services.upgrade),
            (4, "trips", v004_trips.upgrade),
            (5, "visits", v005_visits.upgrade),
            (6, "visit_notes", v006_visit_notes.upgrade),
            (7, "expenses", v007_expenses.upgrade),
        ]

        known_versions = set()

        for version, table, upgrade in migrations:
            known_versions.add(version)

        unknown_versions = applied_versions - known_versions

        if unknown_versions:
            raise RuntimeError(
                f"Unknown migration versions: {sorted(unknown_versions)}"
            )

        if applied_versions:
            last_version = max(applied_versions)
            required_versions = set(range(1, last_version + 1))

            if applied_versions != required_versions:
                raise RuntimeError("Migration history contains missing versions")

        existing_tables = set()

        for version, table, upgrade in migrations:
            if table_exists(cursor, table):
                validate_table(cursor, table)
                existing_tables.add(table)

            elif version in applied_versions:
                raise RuntimeError(
                    f"Migration {version} is recorded but table {table} is missing"
                )

        for version, table, upgrade in migrations:
            if version in applied_versions:
                continue

            if table not in existing_tables:
                upgrade(cursor)
                validate_table(cursor, table)

            record_migration(cursor, version)
            connection.commit()

    except Exception as error:
        print(f"Migration error: {error}")

        if connection is not None:
            connection.rollback()

        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit("Run database migrations through install.sh")
