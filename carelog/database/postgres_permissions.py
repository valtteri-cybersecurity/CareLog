from psycopg import sql

from carelog.database.postgres_connection import get_postgres_connection


# The migration account creates and owns the CareLog tables.
MIGRATION_USER = "carelog_migrator"

# Table privileges of the application account. Grant only what the
# repositories need.
APP_TABLE_PRIVILEGES = {
    "clients": ("SELECT", "INSERT", "UPDATE"),
    "services": ("SELECT", "INSERT", "UPDATE"),
    "trips": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "visits": ("SELECT", "INSERT", "UPDATE"),
    "visit_notes": ("SELECT", "INSERT", "UPDATE"),
    "expenses": ("SELECT", "INSERT", "UPDATE"),
    "visit_trip_legs": ("SELECT", "INSERT", "DELETE"),
}

# The application may read only these columns of users. It cannot read
# password_hash.
APP_USERS_COLUMNS = ("id", "email", "display_name", "role", "is_active")

# All table privileges in PostgreSQL 16.
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)

# Privileges that can also be granted for single columns.
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


def grant_app_permissions(cursor, app_user, owner_user):
    # sql.Identifier quotes the account names safely. The privilege and
    # table names are fixed values from this file.
    user = sql.Identifier(app_user)
    owner = sql.Identifier(owner_user)

    # Remove earlier privileges first, so that only the listed ones remain.
    # Revoking a table privilege also revokes its column privileges.
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(user)
    )
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(user)
    )

    # Default privileges are given automatically to tables and sequences
    # that owner_user creates later. The application gets no default
    # privileges. A REVOKE IN SCHEMA public does not remove a default that
    # was granted for all schemas, so both kinds are removed.
    default_privileges = [
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM {}",
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
        "REVOKE ALL ON SEQUENCES FROM {}",
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE ALL ON TABLES FROM {}",
        "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE ALL ON SEQUENCES FROM {}",
    ]

    for query in default_privileges:
        cursor.execute(sql.SQL(query).format(owner, user))

    for table, privileges in APP_TABLE_PRIVILEGES.items():
        query = sql.SQL("GRANT " + ", ".join(privileges) + " ON TABLE {} TO {}")
        cursor.execute(query.format(sql.Identifier(table), user))

    query = sql.SQL(
        "GRANT SELECT (" + ", ".join(APP_USERS_COLUMNS) + ") ON TABLE users TO {}"
    )
    cursor.execute(query.format(user))


def check_app_permissions(cursor, app_user):
    # The application account must be an ordinary login account.
    cursor.execute("""
        SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
        FROM pg_roles
        WHERE rolname = %s
    """, (app_user,))

    result = cursor.fetchone()

    if result is None:
        raise RuntimeError("Application account is missing")

    for value in result:
        if value:
            raise RuntimeError(
                "Application account has excessive role attributes. "
                "Manual review required"
            )

    # A member of another role also gets the privileges of that role.
    cursor.execute("""
        SELECT COUNT(*)
        FROM pg_auth_members AS m
        JOIN pg_roles AS r
          ON r.oid = m.member
        WHERE r.rolname = %s
    """, (app_user,))

    if cursor.fetchone()[0] != 0:
        raise RuntimeError(
            "Application account is a member of another role. "
            "Manual review required"
        )

    # The owner of a table, schema or database can always change it.
    cursor.execute("""
        SELECT
            (SELECT COUNT(*) FROM pg_class WHERE relowner = r.oid),
            (SELECT COUNT(*) FROM pg_namespace WHERE nspowner = r.oid),
            (SELECT COUNT(*) FROM pg_database
             WHERE datname = current_database() AND datdba = r.oid)
        FROM pg_roles AS r
        WHERE r.rolname = %s
    """, (app_user,))

    for count in cursor.fetchone():
        if count != 0:
            raise RuntimeError(
                "Application account owns database objects. "
                "Manual review required"
            )

    # CREATE would allow new tables in the schema or new schemas.
    cursor.execute("""
        SELECT has_schema_privilege(%s, 'public', 'CREATE'),
               has_database_privilege(%s, current_database(), 'CREATE')
    """, (app_user, app_user))

    for value in cursor.fetchone():
        if value:
            raise RuntimeError(
                "Application account can create database objects. "
                "Manual review required"
            )

    # Default privileges of any account must not give the application
    # privileges on tables (r) or sequences (S) created later. Grants to
    # PUBLIC (grantee 0) reach every account, so they are checked too.
    # PostgreSQL gives PUBLIC no default privileges on tables or sequences,
    # so such a row is always an added grant. A row with no schema
    # (defaclnamespace 0) applies to all schemas.
    cursor.execute("""
        SELECT a.grantee, r.rolname, d.defaclnamespace, d.defaclobjtype,
               a.privilege_type
        FROM pg_default_acl AS d
        JOIN pg_roles AS r
          ON r.oid = d.defaclrole
        CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
        WHERE (a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
               OR a.grantee = 0)
          AND d.defaclobjtype IN ('r', 'S')
        ORDER BY a.grantee, r.rolname, d.defaclobjtype, a.privilege_type
    """, (app_user,))

    result = cursor.fetchone()

    if result is not None:
        grantee, owner, schema, object_type, privilege = result

        if grantee == 0:
            receiver = "PUBLIC"
        else:
            receiver = "Application account"

        if object_type == "r":
            objects = "tables"
        else:
            objects = "sequences"

        if schema == 0:
            scope = "in all schemas"
        else:
            scope = "in a schema"

        # The migration account cannot safely remove grants of other
        # accounts or grants to PUBLIC, so an administrator must do it.
        raise RuntimeError(
            f"{receiver} has default privilege {privilege} on new "
            f"{objects} of {owner} {scope}. An administrator must remove it "
            "with ALTER DEFAULT PRIVILEGES. Manual review required"
        )

    # Every table in the schema, including schema_migrations, must have
    # exactly the listed privileges.
    cursor.execute("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)

    tables = []

    for row in cursor.fetchall():
        tables.append(row[0])

    for table in tables:
        expected_privileges = APP_TABLE_PRIVILEGES.get(table, ())

        for privilege in TABLE_PRIVILEGES:
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (app_user, table, privilege)
            )
            table_privilege = cursor.fetchone()[0]

            # has_any_column_privilege() is also true for a privilege on
            # only one column.
            column_privilege = False

            if privilege in COLUMN_PRIVILEGES:
                cursor.execute(
                    "SELECT has_any_column_privilege(%s, %s, %s)",
                    (app_user, table, privilege)
                )
                column_privilege = cursor.fetchone()[0]

            if privilege in expected_privileges:
                if not table_privilege:
                    raise RuntimeError(
                        f"Application account is missing privilege: "
                        f"{privilege} on {table}"
                    )

            # users is checked column by column below.
            elif table == "users" and privilege == "SELECT":
                if table_privilege:
                    raise RuntimeError(
                        "Application account can read every users column. "
                        "Manual review required"
                    )

            elif table_privilege or column_privilege:
                raise RuntimeError(
                    f"Application account has excessive privilege: "
                    f"{privilege} on {table}. Manual review required"
                )

    if "users" in tables:
        cursor.execute("""
            SELECT a.attname, has_column_privilege(%s, 'users', a.attname, 'SELECT')
            FROM pg_attribute AS a
            WHERE a.attrelid = 'users'::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
        """, (app_user,))

        for column, can_read in cursor.fetchall():
            if column in APP_USERS_COLUMNS:
                if not can_read:
                    raise RuntimeError(
                        f"Application account cannot read users.{column}"
                    )

            elif can_read:
                raise RuntimeError(
                    f"Application account can read users.{column}. "
                    "Manual review required"
                )

    # Identity columns do not need sequence privileges. Changing a sequence
    # could break the id values of new rows.
    cursor.execute("""
        SELECT sequencename
        FROM pg_sequences
        WHERE schemaname = 'public'
        ORDER BY sequencename
    """)

    sequences = []

    for row in cursor.fetchall():
        sequences.append(row[0])

    for sequence in sequences:
        cursor.execute(
            "SELECT has_sequence_privilege(%s, %s, 'USAGE, SELECT, UPDATE')",
            (app_user, sequence)
        )

        if cursor.fetchone()[0]:
            raise RuntimeError(
                f"Application account has privileges on sequence {sequence}. "
                "Manual review required"
            )


def apply_app_permissions(app_user, database=None, *, password):
    if not password:
        raise ValueError("A password for carelog_migrator is required")

    connection = None
    cursor = None

    try:
        # The migration account owns the tables, so it can grant and
        # revoke their privileges.
        connection = get_postgres_connection(
            database=database,
            user=MIGRATION_USER,
            password=password,
        )

        cursor = connection.cursor()
        grant_app_permissions(cursor, app_user, MIGRATION_USER)
        check_app_permissions(cursor, app_user)
        connection.commit()

    except Exception:
        if connection is not None:
            connection.rollback()

        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
