from carelog.database.connection import get_connection
from carelog.database.migrations import (
    v001_users,
    v002_clients,
    v003_services,
    v004_trips,
    v005_visits,
    v006_visit_notes,
    v007_expenses,
    v008_business_constraints,
    v009_visit_scheduling,
    v010_visit_constraints,
    v011_visit_trip_legs,
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
    "visit_trip_legs": [
        ("id", "int", "NO", None),
        ("visit_id", "int", "NO", None),
        ("position", "int", "NO", None),
        ("start_location", "varchar(255)", "NO", None),
        ("destination", "varchar(255)", "NO", None),
        ("distance_km", "decimal(10,2)", "YES", None),
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
    "visit_trip_legs": [
        ("visit_id", "visits", "id", "RESTRICT", "RESTRICT"),
    ],
}


# Expected CHECK constraints added by migration v008.
# Keep these definitions consistent with v008_business_constraints.py.
EXPECTED_CHECKS = {
    ("clients", "chk_clients_distance"): "distance_from_home_km>=0",
    ("services", "chk_services_rate"): "default_hourly_rate>=0",
    ("trips", "chk_trips_distance"): "distance_km>=0",
    ("visits", "chk_visits_distance"): "distance_km>=0",
    ("visits", "chk_visits_price"): "price>=0",
    ("visits", "chk_visits_time"): "ended_at>=started_at",
    ("visit_notes", "chk_notes_content"): "trim(content)<>''",
    ("expenses", "chk_expenses_amount"): "amount>0",
}


# Columns added to the end of the visits table by migration v009.
# Keep these definitions consistent with v009_visit_scheduling.py.
EXPECTED_V009_COLUMNS = [
    ("planned_date", "date", "YES", None),
    ("completed_date", "date", "YES", None),
    ("planned_duration_minutes", "int", "YES", None),
    ("duration_minutes", "int", "YES", None),
]


# Expected CHECK constraints added by migration v010.
# Keep these definitions consistent with v010_visit_constraints.py.
EXPECTED_V010_CHECKS = {
    ("visits", "chk_visits_planned_duration"): "planned_duration_minutes>0",
    ("visits", "chk_visits_duration"): "duration_minutes>0",
    ("visits", "chk_visits_priority"): "prioritybetween1and3",
    ("visits", "chk_visits_status"): "statusin('planned','completed','cancelled')",
}


# Expected CHECK constraints created together with the table in v011.
# Keep these definitions consistent with v011_visit_trip_legs.py.
EXPECTED_V011_CHECKS = {
    ("visit_trip_legs", "chk_trip_legs_position"): "position>0",
    ("visit_trip_legs", "chk_trip_legs_distance"): "distance_km>=0",
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


def validate_table(cursor, table, require_v009=False):
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

    expected_columns = EXPECTED_COLUMNS[table]

    # Before v009 is recorded, visits may still lack the v009 columns.
    # It may also already have all of them if a previous run crashed
    # after ALTER TABLE but before recording the migration.
    if table == "visits":
        columns_with_v009 = EXPECTED_COLUMNS["visits"] + EXPECTED_V009_COLUMNS

        if require_v009 or columns == columns_with_v009:
            expected_columns = columns_with_v009

    if columns != expected_columns:
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
    elif table == "visit_trip_legs":
        expected_unique_columns = [("visit_id", None), ("position", None)]

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


def normalize_check_clause(clause):
    # MySQL may escape quotes in CHECK_CLAUSE, for example \'planned\'.
    clause = clause.replace("\\'", "'")

    # Ignore MySQL formatting without changing quoted string values.
    clause = clause.lower().replace("`", "")
    clause = clause.replace("_utf8mb4", "").replace("_utf8mb3", "")

    normalized = []
    in_string = False

    for char in clause:
        if char == "'":
            in_string = not in_string

        if char.isspace() and not in_string:
            continue

        normalized.append(char)

    clause = "".join(normalized)

    # MySQL can spell TRIM(content) as TRIM(BOTH ' ' FROM content).
    clause = clause.replace("trim(both' 'fromcontent)", "trim(content)")

    # MySQL may add parentheses around an empty string literal.
    clause = clause.replace("<>('')", "<>''")

    # Remove only parentheses enclosing the entire expression.
    while clause.startswith("(") and clause.endswith(")"):
        depth = 0
        outer = True

        for index, char in enumerate(clause):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(clause) - 1:
                    outer = False
                    break

        if not outer:
            break

        clause = clause[1:-1]

    return clause


def validate_business_constraints(
    cursor,
    require_v008=True,
    require_v010=False,
    require_v011=False
):
    cursor.execute("""
        SELECT t.TABLE_NAME, t.CONSTRAINT_NAME, t.ENFORCED, c.CHECK_CLAUSE
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS t
        JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS AS c
          ON t.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA
         AND t.CONSTRAINT_NAME = c.CONSTRAINT_NAME
        WHERE t.TABLE_SCHEMA = DATABASE()
          AND t.CONSTRAINT_TYPE = 'CHECK'
    """)

    found = set()

    for table, name, enforced, clause in cursor.fetchall():
        key = (table, name)
        expected = EXPECTED_CHECKS.get(key)

        if expected is None:
            expected = EXPECTED_V010_CHECKS.get(key)

        if expected is None:
            expected = EXPECTED_V011_CHECKS.get(key)

        if expected is None:
            raise RuntimeError(f"Unexpected CHECK constraint: {table}.{name}")

        actual = normalize_check_clause(clause)

        if enforced != "YES" or actual != expected:
            raise RuntimeError(
                f"Invalid CHECK constraint: {table}.{name} "
                f"(expected={expected!r}, actual={actual!r}, "
                f"MySQL={clause!r}, enforced={enforced!r})"
            )

        found.add(key)

    if require_v008:
        missing = sorted(set(EXPECTED_CHECKS) - found)

        if missing:
            raise RuntimeError(f"Missing CHECK constraints: {missing}")

    if require_v010:
        missing = sorted(set(EXPECTED_V010_CHECKS) - found)

        if missing:
            raise RuntimeError(f"Missing CHECK constraints: {missing}")

    if require_v011:
        missing = sorted(set(EXPECTED_V011_CHECKS) - found)

        if missing:
            raise RuntimeError(f"Missing CHECK constraints: {missing}")


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
            (8, None, v008_business_constraints.upgrade),
            (9, None, v009_visit_scheduling.upgrade),
            (10, None, v010_visit_constraints.upgrade),
            (11, "visit_trip_legs", v011_visit_trip_legs.upgrade),
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
            if table is None:
                continue

            if table_exists(cursor, table):
                validate_table(
                    cursor,
                    table,
                    require_v009=9 in applied_versions,
                )
                existing_tables.add(table)

            elif version in applied_versions:
                raise RuntimeError(
                    f"Migration {version} is recorded but table {table} is missing"
                )

        # Check existing constraints before attempting a partly applied
        # v008 or v010. The v011 table is created with its constraints in
        # one statement, so if the table exists, they must exist too.
        validate_business_constraints(
            cursor,
            require_v008=8 in applied_versions,
            require_v010=10 in applied_versions,
            require_v011="visit_trip_legs" in existing_tables,
        )

        for version, table, upgrade in migrations:
            if version in applied_versions:
                continue

            # Migrations 8–10 change existing tables. Their upgrade
            # functions skip the changes that already exist.
            if version == 8:
                upgrade(cursor)
                validate_business_constraints(cursor, require_v008=True)
            elif version == 9:
                upgrade(cursor)
                validate_table(cursor, "visits", require_v009=True)
            elif version == 10:
                upgrade(cursor)
                validate_business_constraints(
                    cursor,
                    require_v008=True,
                    require_v010=True,
                )
            elif table not in existing_tables:
                upgrade(cursor)
                validate_table(cursor, table)

                if version == 11:
                    validate_business_constraints(
                        cursor,
                        require_v008=True,
                        require_v010=True,
                        require_v011=True,
                    )

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