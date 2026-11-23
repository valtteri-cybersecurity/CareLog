from carelog.database.postgres_connection import get_postgres_connection
from carelog.database.postgres_migrations import (
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


# Migrations in order: version, created table (None if the migration
# changes existing tables), upgrade function.
MIGRATIONS = [
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


# Default value of the time columns, as PostgreSQL shows it.
UTC_NOW = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'::text)"


# Expected column structure: name, type, nullable, default value.
# Types and defaults are written as PostgreSQL shows them in its system
# catalog. Keep these definitions consistent with the migration files.
EXPECTED_COLUMNS = {
    "users": [
        ("id", "integer", "NO", None),
        ("email", "character varying(254)", "NO", None),
        ("display_name", "character varying(150)", "NO", None),
        ("password_hash", "character varying(255)", "NO", None),
        ("role", "character varying(20)", "NO", "'worker'::character varying"),
        ("is_active", "boolean", "NO", "true"),
        ("created_at", "timestamp without time zone", "NO", UTC_NOW),
        ("updated_at", "timestamp without time zone", "NO", UTC_NOW),
    ],
    "clients": [
        ("id", "integer", "NO", None),
        ("first_name", "character varying(100)", "NO", None),
        ("last_name", "character varying(100)", "NO", None),
        ("phone", "character varying(50)", "YES", None),
        ("email", "character varying(255)", "YES", None),
        ("street_address", "character varying(255)", "YES", None),
        ("postal_code", "character varying(20)", "YES", None),
        ("city", "character varying(100)", "YES", None),
        ("distance_from_home_km", "numeric(10,2)", "YES", None),
        ("archived_at", "timestamp without time zone", "YES", None),
        ("created_at", "timestamp without time zone", "NO", UTC_NOW),
        ("updated_at", "timestamp without time zone", "NO", UTC_NOW),
    ],
    "services": [
        ("id", "integer", "NO", None),
        ("name", "character varying(150)", "NO", None),
        ("description", "text", "YES", None),
        ("default_hourly_rate", "numeric(10,2)", "YES", None),
    ],
    "trips": [
        ("id", "integer", "NO", None),
        ("client_id", "integer", "NO", None),
        ("start_location", "character varying(255)", "NO", None),
        ("destination", "character varying(255)", "NO", None),
        ("distance_km", "numeric(10,2)", "YES", None),
    ],
    "visits": [
        ("id", "integer", "NO", None),
        ("client_id", "integer", "NO", None),
        ("service_id", "integer", "NO", None),
        ("status", "character varying(20)", "NO", "'planned'::character varying"),
        ("priority", "smallint", "NO", "2"),
        ("planned_week", "date", "YES", None),
        ("planned_at", "timestamp without time zone", "YES", None),
        ("started_at", "timestamp without time zone", "YES", None),
        ("ended_at", "timestamp without time zone", "YES", None),
        ("description", "text", "YES", None),
        ("distance_km", "numeric(10,2)", "YES", None),
        ("price", "numeric(10,2)", "YES", None),
        ("created_at", "timestamp without time zone", "NO", UTC_NOW),
        ("updated_at", "timestamp without time zone", "NO", UTC_NOW),
    ],
    "visit_notes": [
        ("id", "integer", "NO", None),
        ("visit_id", "integer", "NO", None),
        ("content", "text", "NO", None),
        ("created_at", "timestamp without time zone", "NO", UTC_NOW),
    ],
    "expenses": [
        ("id", "integer", "NO", None),
        ("visit_id", "integer", "YES", None),
        ("expense_date", "date", "NO", None),
        ("amount", "numeric(10,2)", "NO", None),
        ("category", "character varying(20)", "NO", None),
        ("description", "character varying(255)", "YES", None),
    ],
    "visit_trip_legs": [
        ("id", "integer", "NO", None),
        ("visit_id", "integer", "NO", None),
        ("position", "integer", "NO", None),
        ("start_location", "character varying(255)", "NO", None),
        ("destination", "character varying(255)", "NO", None),
        ("distance_km", "numeric(10,2)", "YES", None),
    ],
}


# Columns added to the end of the visits table by migration v009.
# Keep these definitions consistent with v009_visit_scheduling.py.
EXPECTED_V009_COLUMNS = [
    ("planned_date", "date", "YES", None),
    ("completed_date", "date", "YES", None),
    ("planned_duration_minutes", "integer", "YES", None),
    ("duration_minutes", "integer", "YES", None),
]


# Unique indexes other than the primary key, as pg_get_indexdef() shows
# them. The users index compares emails without letter case.
EXPECTED_UNIQUE_INDEXES = {
    "users": [
        "CREATE UNIQUE INDEX uq_users_email ON public.users "
        "USING btree (lower((email)::text))",
    ],
    "visit_trip_legs": [
        "CREATE UNIQUE INDEX uq_trip_legs_visit_position "
        "ON public.visit_trip_legs USING btree (visit_id, \"position\")",
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


# Foreign key rules as single letters in pg_constraint. NO ACTION (a)
# works like RESTRICT here, as in the MySQL version.
FOREIGN_KEY_RULES = {
    "a": "RESTRICT",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


# Triggers that keep updated_at current, as pg_get_triggerdef() shows them.
EXPECTED_TRIGGERS = {
    "users": [
        "CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()",
    ],
    "clients": [
        "CREATE TRIGGER trg_clients_updated_at BEFORE UPDATE ON public.clients "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()",
    ],
    "visits": [
        "CREATE TRIGGER trg_visits_updated_at BEFORE UPDATE ON public.visits "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()",
    ],
}


# Expected CHECK constraints, as pg_get_constraintdef() shows them.
# The user role is a CHECK constraint instead of a MySQL ENUM.
EXPECTED_V001_CHECKS = {
    ("users", "chk_users_role"): (
        "CHECK (((role)::text = ANY ((ARRAY['admin'::character varying, "
        "'worker'::character varying])::text[])))"
    ),
}


# Expected CHECK constraints added by migration v008.
# Keep these definitions consistent with v008_business_constraints.py.
EXPECTED_CHECKS = {
    ("clients", "chk_clients_distance"): (
        "CHECK ((distance_from_home_km >= (0)::numeric))"
    ),
    ("services", "chk_services_rate"): (
        "CHECK ((default_hourly_rate >= (0)::numeric))"
    ),
    ("trips", "chk_trips_distance"): "CHECK ((distance_km >= (0)::numeric))",
    ("visits", "chk_visits_distance"): "CHECK ((distance_km >= (0)::numeric))",
    ("visits", "chk_visits_price"): "CHECK ((price >= (0)::numeric))",
    ("visits", "chk_visits_time"): "CHECK ((ended_at >= started_at))",
    ("visit_notes", "chk_notes_content"): (
        "CHECK ((TRIM(BOTH FROM content) <> ''::text))"
    ),
    ("expenses", "chk_expenses_amount"): "CHECK ((amount > (0)::numeric))",
}


# Expected CHECK constraints added by migration v010.
# Keep these definitions consistent with v010_visit_constraints.py.
EXPECTED_V010_CHECKS = {
    ("visits", "chk_visits_planned_duration"): (
        "CHECK ((planned_duration_minutes > 0))"
    ),
    ("visits", "chk_visits_duration"): "CHECK ((duration_minutes > 0))",
    ("visits", "chk_visits_priority"): (
        "CHECK (((priority >= 1) AND (priority <= 3)))"
    ),
    ("visits", "chk_visits_status"): (
        "CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, "
        "'completed'::character varying, "
        "'cancelled'::character varying])::text[])))"
    ),
}


# Expected CHECK constraints created together with the table in v011.
# Keep these definitions consistent with v011_visit_trip_legs.py.
EXPECTED_V011_CHECKS = {
    ("visit_trip_legs", "chk_trip_legs_position"): "CHECK ((\"position\" > 0))",
    ("visit_trip_legs", "chk_trip_legs_distance"): (
        "CHECK ((distance_km >= (0)::numeric))"
    ),
}


def check_schema(cursor):
    # CareLog tables belong to the public schema. If the migration account
    # had its own schema first in search_path, the tables would be created
    # there and the application would not find them.
    cursor.execute("SELECT current_schema()")
    schema = cursor.fetchone()[0]

    if schema != "public":
        raise RuntimeError(f"Invalid schema for migrations: {schema}")


def create_migrations_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL
                DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
        )
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
        SELECT 1
        FROM pg_tables
        WHERE schemaname = current_schema()
          AND tablename = %s
    """, (table,))

    return cursor.fetchone() is not None


def validate_table(cursor, table, applied_versions):
    # pg_attribute holds the columns and pg_attrdef their default values.
    # attidentity is 'd' for GENERATED BY DEFAULT AS IDENTITY.
    cursor.execute("""
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod),
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid),
               a.attidentity
        FROM pg_attribute AS a
        LEFT JOIN pg_attrdef AS d
          ON d.adrelid = a.attrelid
         AND d.adnum = a.attnum
        WHERE a.attrelid = %s::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
    """, (table,))

    columns = []

    for column in cursor.fetchall():
        name, column_type, not_null, default, identity = column

        if not_null:
            nullable = "NO"
        else:
            nullable = "YES"

        columns.append((name, column_type, nullable, default))

        expected_identity = ""

        if name == "id":
            expected_identity = "d"

        if identity != expected_identity:
            raise RuntimeError(f"Invalid column settings: {table}.{name}")

    expected_columns = EXPECTED_COLUMNS[table]

    if table == "visits" and 9 in applied_versions:
        expected_columns = EXPECTED_COLUMNS["visits"] + EXPECTED_V009_COLUMNS

    if columns != expected_columns:
        raise RuntimeError(f"Invalid columns in table: {table}")

    # contype 'p' is a primary key. conkey lists its column numbers.
    cursor.execute("""
        SELECT a.attname
        FROM pg_constraint AS c
        JOIN pg_attribute AS a
          ON a.attrelid = c.conrelid
         AND a.attnum = ANY (c.conkey)
        WHERE c.conrelid = %s::regclass
          AND c.contype = 'p'
        ORDER BY a.attnum
    """, (table,))

    primary_key = []

    for row in cursor.fetchall():
        primary_key.append(row[0])

    if primary_key != ["id"]:
        raise RuntimeError(f"Invalid primary key in table: {table}")

    cursor.execute("""
        SELECT pg_get_indexdef(indexrelid)
        FROM pg_index
        WHERE indrelid = %s::regclass
          AND indisunique
          AND NOT indisprimary
        ORDER BY 1
    """, (table,))

    unique_indexes = []

    for row in cursor.fetchall():
        unique_indexes.append(row[0])

    if unique_indexes != EXPECTED_UNIQUE_INDEXES.get(table, []):
        raise RuntimeError(f"Invalid unique constraints in table: {table}")

    # contype 'f' is a foreign key. Every CareLog foreign key has one column.
    cursor.execute("""
        SELECT a.attname,
               n.nspname,
               r.relname,
               ra.attname,
               c.confdeltype,
               c.confupdtype,
               c.convalidated,
               cardinality(c.conkey)
        FROM pg_constraint AS c
        JOIN pg_attribute AS a
          ON a.attrelid = c.conrelid
         AND a.attnum = c.conkey[1]
        JOIN pg_class AS r
          ON r.oid = c.confrelid
        JOIN pg_namespace AS n
          ON n.oid = r.relnamespace
        JOIN pg_attribute AS ra
          ON ra.attrelid = c.confrelid
         AND ra.attnum = c.confkey[1]
        WHERE c.conrelid = %s::regclass
          AND c.contype = 'f'
        ORDER BY a.attname
    """, (table,))

    foreign_key_rows = cursor.fetchall()

    foreign_keys = []

    for row in foreign_key_rows:
        (
            column,
            schema,
            reference_table,
            reference_column,
            delete_rule,
            update_rule,
            validated,
            column_count,
        ) = row

        if schema != "public":
            raise RuntimeError(f"Foreign key references another schema: {table}")

        if not validated or column_count != 1:
            raise RuntimeError(f"Invalid foreign keys in table: {table}")

        foreign_key = (
            column,
            reference_table,
            reference_column,
            FOREIGN_KEY_RULES[delete_rule],
            FOREIGN_KEY_RULES[update_rule],
        )

        foreign_keys.append(foreign_key)

    expected_foreign_keys = EXPECTED_FOREIGN_KEYS.get(table, [])

    if foreign_keys != expected_foreign_keys:
        raise RuntimeError(f"Invalid foreign keys in table: {table}")

    # Disabled triggers (tgenabled 'D') would not update updated_at.
    cursor.execute("""
        SELECT pg_get_triggerdef(oid)
        FROM pg_trigger
        WHERE tgrelid = %s::regclass
          AND NOT tgisinternal
          AND tgenabled <> 'D'
        ORDER BY tgname
    """, (table,))

    triggers = []

    for row in cursor.fetchall():
        triggers.append(row[0])

    if triggers != EXPECTED_TRIGGERS.get(table, []):
        raise RuntimeError(f"Invalid triggers in table: {table}")


def validate_business_constraints(cursor, applied_versions):
    # contype 'c' is a CHECK constraint. convalidated is false for a
    # constraint added with NOT VALID, which does not check old rows.
    cursor.execute("""
        SELECT r.relname, c.conname, c.convalidated, pg_get_constraintdef(c.oid)
        FROM pg_constraint AS c
        JOIN pg_class AS r
          ON r.oid = c.conrelid
        WHERE r.relnamespace = current_schema()::regnamespace
          AND c.contype = 'c'
    """)

    # Every CHECK constraint of an applied migration must exist, and no
    # other CHECK constraints are allowed.
    expected_checks = {}

    if 1 in applied_versions:
        expected_checks.update(EXPECTED_V001_CHECKS)

    if 8 in applied_versions:
        expected_checks.update(EXPECTED_CHECKS)

    if 10 in applied_versions:
        expected_checks.update(EXPECTED_V010_CHECKS)

    if 11 in applied_versions:
        expected_checks.update(EXPECTED_V011_CHECKS)

    found = set()

    for table, name, validated, definition in cursor.fetchall():
        key = (table, name)
        expected = expected_checks.get(key)

        if expected is None:
            raise RuntimeError(f"Unexpected CHECK constraint: {table}.{name}")

        if not validated or definition != expected:
            raise RuntimeError(
                f"Invalid CHECK constraint: {table}.{name} "
                f"(expected={expected!r}, actual={definition!r}, "
                f"validated={validated!r})"
            )

        found.add(key)

    missing = sorted(set(expected_checks) - found)

    if missing:
        raise RuntimeError(f"Missing CHECK constraints: {missing}")


def validate_schema(cursor, applied_versions):
    for version, table, upgrade in MIGRATIONS:
        if table is not None and version in applied_versions:
            validate_table(cursor, table, applied_versions)

    validate_business_constraints(cursor, applied_versions)


def run_postgres_migrations(database=None, *, password):
    if not password:
        raise ValueError("A password for carelog_migrator is required")

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection(
            database=database,
            user="carelog_migrator",
            password=password,
        )

        cursor = connection.cursor()
        check_schema(cursor)
        create_migrations_table(cursor)
        applied_versions = get_applied_versions(cursor)

        known_versions = set()

        for version, table, upgrade in MIGRATIONS:
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

        # PostgreSQL rolls back a failed migration completely, so a table
        # can exist without its version only if it was created by hand.
        for version, table, upgrade in MIGRATIONS:
            if table is None:
                continue

            if table_exists(cursor, table):
                if version not in applied_versions:
                    raise RuntimeError(
                        f"Table {table} exists without migration history"
                    )

            elif version in applied_versions:
                raise RuntimeError(
                    f"Migration {version} is recorded but table {table} is missing"
                )

        # Check that the existing tables match the recorded history
        # before anything is changed.
        validate_schema(cursor, applied_versions)
        connection.commit()

        for version, table, upgrade in MIGRATIONS:
            if version in applied_versions:
                continue

            # The changes, their check and the version record are saved
            # in one transaction: all of them or none.
            upgrade(cursor)
            record_migration(cursor, version)
            applied_versions.add(version)
            validate_schema(cursor, applied_versions)
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
    raise SystemExit("Run database migrations through install.sh --postgres")
