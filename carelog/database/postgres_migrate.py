import re

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
    v012_foreign_key_indexes,
    v013_visit_note_history,
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
    (12, None, v012_foreign_key_indexes.upgrade),
    (13, "visit_note_history", v013_visit_note_history.upgrade),
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
    "visit_note_history": [
        ("id", "integer", "NO", None),
        ("note_id", "integer", "NO", None),
        ("old_content", "text", "NO", None),
        ("new_content", "text", "NO", None),
        ("edited_at", "timestamp without time zone", "NO", UTC_NOW),
        ("edited_by_user_id", "integer", "YES", None),
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

# Column added to the end of the visit_notes table by migration v013.
# Keep this definition consistent with v013_visit_note_history.py.
EXPECTED_V013_COLUMNS = [
    ("updated_at", "timestamp without time zone", "NO", UTC_NOW),
]


# Indexes other than the primary key: version that creates the index,
# index name, unique, and its key columns as PostgreSQL shows them.
# The users index compares emails without letter case.
EXPECTED_INDEXES = {
    "users": [
        (1, "uq_users_email", True, ["lower(email::text)"]),
    ],
    "trips": [
        (12, "idx_trips_client_id", False, ["client_id"]),
    ],
    "visits": [
        (12, "idx_visits_client_id", False, ["client_id"]),
    ],
    "visit_notes": [
        (12, "idx_visit_notes_visit_id", False, ["visit_id"]),
    ],
    "expenses": [
        (12, "idx_expenses_visit_id", False, ["visit_id"]),
    ],
    "visit_trip_legs": [
        (11, "uq_trip_legs_visit_position", True, ["visit_id", "\"position\""]),
    ],
    "visit_note_history": [
        (13, "idx_visit_note_history_note_id", False, ["note_id"]),
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
    "visit_note_history": [
        ("edited_by_user_id", "users", "id", "RESTRICT", "RESTRICT"),
        ("note_id", "visit_notes", "id", "RESTRICT", "RESTRICT"),
    ],
}


# Foreign key rules as single letters in pg_constraint. NO ACTION (a)
# works like RESTRICT here.
FOREIGN_KEY_RULES = {
    "a": "RESTRICT",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


# Tables whose updated_at is kept current by the trigger
# trg_<table>_updated_at, which calls set_updated_at().
UPDATED_AT_TABLES = ("users", "clients", "visits")

# pg_trigger.tgtype of a BEFORE UPDATE FOR EACH ROW trigger:
# 1 (FOR EACH ROW) + 2 (BEFORE) + 16 (UPDATE).
BEFORE_UPDATE_ROW_TRIGGER = 19

# The note history trigger of migration v013 and its function. Keep these
# consistent with v013_visit_note_history.py.
NOTE_HISTORY_TRIGGER = "trg_visit_notes_history"
NOTE_HISTORY_FUNCTION = "save_visit_note_history"
NOTE_HISTORY_SEARCH_PATH = ["search_path=pg_catalog, pg_temp"]


# CHECK constraints by the migration that creates them:
# (table, constraint name): the condition. The conditions are written as
# PostgreSQL stores them (for example IN becomes = ANY), but without the
# type casts and parentheses it adds; see normalize_check_condition().
# Keep these consistent with the migration files.
EXPECTED_CHECKS = {
    1: {
        ("users", "chk_users_role"): "role = ANY (ARRAY['admin', 'worker'])",
    },
    8: {
        ("clients", "chk_clients_distance"): "distance_from_home_km >= 0",
        ("services", "chk_services_rate"): "default_hourly_rate >= 0",
        ("trips", "chk_trips_distance"): "distance_km >= 0",
        ("visits", "chk_visits_distance"): "distance_km >= 0",
        ("visits", "chk_visits_price"): "price >= 0",
        ("visits", "chk_visits_time"): "ended_at >= started_at",
        ("visit_notes", "chk_notes_content"): "TRIM(BOTH FROM content) <> ''",
        ("expenses", "chk_expenses_amount"): "amount > 0",
    },
    10: {
        ("visits", "chk_visits_planned_duration"): "planned_duration_minutes > 0",
        ("visits", "chk_visits_duration"): "duration_minutes > 0",
        ("visits", "chk_visits_priority"): "priority >= 1 AND priority <= 3",
        (
            "visits",
            "chk_visits_status",
        ): "status = ANY (ARRAY['planned', 'completed', 'cancelled'])",
    },
    11: {
        ("visit_trip_legs", "chk_trip_legs_position"): "position > 0",
        ("visit_trip_legs", "chk_trip_legs_distance"): "distance_km >= 0",
    },
}


def normalize_check_condition(condition):
    # pg_get_constraintdef() shows for example
    # CHECK ((amount > (0)::numeric)). Remove the word CHECK, the type
    # casts (::numeric), parentheses, quotes and spaces, so that only the
    # condition itself is compared: amount>0. A changed operator, number,
    # column or value is still a difference.
    condition = condition.lower()
    condition = condition.removeprefix("check ")
    condition = re.sub(r"::[a-z ]+(\[\])?", "", condition)

    for character in ("(", ")", '"', " "):
        condition = condition.replace(character, "")

    return condition


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

    if table == "visit_notes" and 13 in applied_versions:
        expected_columns = EXPECTED_COLUMNS["visit_notes"] + EXPECTED_V013_COLUMNS

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

    # pg_index holds the indexes. pg_get_indexdef(index, k, true) shows
    # key column number k. An invalid index is not used by PostgreSQL.
    cursor.execute("""
        SELECT c.relname,
               i.indisunique,
               i.indisvalid,
               ARRAY(
                   SELECT pg_get_indexdef(i.indexrelid, k, true)
                   FROM generate_series(1, i.indnkeyatts) AS k
                   ORDER BY k
               )
        FROM pg_index AS i
        JOIN pg_class AS c
          ON c.oid = i.indexrelid
        WHERE i.indrelid = %s::regclass
          AND NOT i.indisprimary
        ORDER BY c.relname
    """, (table,))

    indexes = []

    for name, unique, valid, keys in cursor.fetchall():
        if not valid:
            raise RuntimeError(f"Invalid index in table: {table}.{name}")

        indexes.append((name, unique, keys))

    expected_indexes = []

    for version, name, unique, keys in EXPECTED_INDEXES.get(table, []):
        if version in applied_versions:
            expected_indexes.append((name, unique, keys))

    expected_indexes.sort()

    if indexes != expected_indexes:
        raise RuntimeError(f"Invalid indexes in table: {table}")

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

    # pg_trigger holds the triggers and pg_proc the function they call.
    # tgenabled is 'O' for an enabled trigger. A disabled trigger would
    # not update updated_at or save the note history.
    cursor.execute("""
        SELECT t.tgname, p.proname, t.tgtype, t.tgenabled
        FROM pg_trigger AS t
        JOIN pg_proc AS p
          ON p.oid = t.tgfoid
        WHERE t.tgrelid = %s::regclass
          AND NOT t.tgisinternal
        ORDER BY t.tgname
    """, (table,))

    triggers = cursor.fetchall()
    expected_triggers = []

    if table in UPDATED_AT_TABLES:
        expected_triggers.append(
            (
                f"trg_{table}_updated_at",
                "set_updated_at",
                BEFORE_UPDATE_ROW_TRIGGER,
                "O",
            )
        )

    if table == "visit_notes" and 13 in applied_versions:
        expected_triggers.append(
            (
                NOTE_HISTORY_TRIGGER,
                NOTE_HISTORY_FUNCTION,
                BEFORE_UPDATE_ROW_TRIGGER,
                "O",
            )
        )

    if triggers != expected_triggers:
        raise RuntimeError(f"Invalid triggers in table: {table}")


def validate_note_history_function(cursor):
    # The history function runs with the rights of its owner (SECURITY
    # DEFINER), so its settings are checked:
    # - the owner is the owner of the history table, not another account
    # - the search path is fixed (proconfig), so the caller cannot change
    #   which tables and functions it finds
    # - only the owner may execute it. proacl NULL means the default
    #   privileges, where PUBLIC may execute every new function.
    cursor.execute("""
        SELECT p.prosecdef,
               p.proconfig,
               p.proowner = r.relowner,
               p.proacl IS NOT NULL,
               EXISTS (
                   SELECT 1
                   FROM aclexplode(p.proacl) AS a
                   WHERE a.grantee <> p.proowner
               )
        FROM pg_proc AS p
        JOIN pg_class AS r
          ON r.oid = 'visit_note_history'::regclass
        WHERE p.pronamespace = current_schema()::regnamespace
          AND p.proname = %s
    """, (NOTE_HISTORY_FUNCTION,))

    rows = cursor.fetchall()

    if len(rows) != 1:
        raise RuntimeError(f"Invalid function: {NOTE_HISTORY_FUNCTION}")

    security_definer, config, owner_matches, has_acl, others_can_execute = rows[0]

    if not security_definer or config != NOTE_HISTORY_SEARCH_PATH:
        raise RuntimeError(f"Invalid function settings: {NOTE_HISTORY_FUNCTION}")

    if not owner_matches:
        raise RuntimeError(f"Invalid function owner: {NOTE_HISTORY_FUNCTION}")

    if not has_acl or others_can_execute:
        raise RuntimeError(f"Invalid function privileges: {NOTE_HISTORY_FUNCTION}")


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

    for version, checks in EXPECTED_CHECKS.items():
        if version in applied_versions:
            expected_checks.update(checks)

    found = set()

    for table, name, validated, definition in cursor.fetchall():
        key = (table, name)
        expected_condition = expected_checks.get(key)

        if expected_condition is None:
            raise RuntimeError(f"Unexpected CHECK constraint: {table}.{name}")

        actual = normalize_check_condition(definition)
        expected = normalize_check_condition(expected_condition)

        if not validated or actual != expected:
            raise RuntimeError(
                f"Invalid CHECK constraint: {table}.{name} "
                f"(expected={expected!r}, actual={actual!r})"
            )

        found.add(key)

    missing = sorted(set(expected_checks) - found)

    if missing:
        raise RuntimeError(f"Missing CHECK constraints: {missing}")


def validate_schema(cursor, applied_versions):
    for version, table, upgrade in MIGRATIONS:
        if table is not None and version in applied_versions:
            validate_table(cursor, table, applied_versions)

    if 13 in applied_versions:
        validate_note_history_function(cursor)

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
