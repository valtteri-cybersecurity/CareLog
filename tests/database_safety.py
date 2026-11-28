from dotenv import dotenv_values


# Safety checks for the PostgreSQL tests. The tests create and drop
# databases and accounts, so they may only use a disposable test server.
#
# No single fact proves that a server is disposable: localhost, a port
# number or a database name can all point to the real CareLog server.
# The tests therefore refuse a server unless every check below passes:
#
# 1. The test settings are complete and valid, and no libpq
#    environment variable can send the connection elsewhere.
# 2. The test account and address are not the application's own
#    (from .env, when the file exists). Checked before connecting.
# 3. The server is marked as disposable.
# 4. The server has no databases other than the PostgreSQL defaults
#    and temporary carelog_test_* databases.
# 5. The postgres database has no tables of its own.
# 6. The server has no CareLog application accounts.

# A disposable test server is marked with this comment on its postgres
# database. Set it only on a server whose data may be lost:
# COMMENT ON DATABASE postgres IS 'carelog-disposable-test-server';
TEST_SERVER_MARKER = "carelog-disposable-test-server"

# The accounts of a real CareLog installation
APPLICATION_ACCOUNTS = ("carelog_app", "carelog_migrator")

# Databases that every PostgreSQL server has
DEFAULT_DATABASES = ("postgres", "template0", "template1")

# The temporary databases of the tests start with this
TEST_DATABASE_PREFIX = "carelog_test_"

LOCAL_HOST_NAMES = ("localhost", "127.0.0.1", "::1")

# libpq environment variables that can send a connection to another
# server than CARELOG_TEST_PG_HOST and CARELOG_TEST_PG_PORT say
REROUTING_LIBPQ_VARIABLES = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")


class DatabaseConnectionBlocked(BaseException):
    # Raised when a test opens a database connection without the
    # verified test server fixtures.
    #
    # This is a BaseException on purpose: "except Exception" blocks in
    # the application or in a test cannot swallow it, so the test always
    # fails instead of continuing quietly.
    pass


class UnsafeTestServerError(Exception):
    # Raised when the test settings or the test server are not safe.
    pass


def read_test_server_settings(environment):
    # Reads the CARELOG_TEST_PG_* settings. Returns None when
    # CARELOG_TEST_PG_USER is not set: the database tests are then
    # skipped and no connection is made. A partial or invalid
    # configuration raises UnsafeTestServerError.
    user = environment.get("CARELOG_TEST_PG_USER", "")

    if not user:
        return None

    host = environment.get("CARELOG_TEST_PG_HOST", "")
    port_text = environment.get("CARELOG_TEST_PG_PORT", "")
    password = environment.get("CARELOG_TEST_PG_PASSWORD", "")

    for variable in REROUTING_LIBPQ_VARIABLES:
        if environment.get(variable):
            raise UnsafeTestServerError(
                f"{variable} is set; it could connect the tests to another server"
            )

    # No defaults: a default port such as 5432 could be a real server
    if not host:
        raise UnsafeTestServerError("CARELOG_TEST_PG_HOST is not set")

    if not port_text:
        raise UnsafeTestServerError("CARELOG_TEST_PG_PORT is not set")

    if not port_text.isdigit():
        raise UnsafeTestServerError("CARELOG_TEST_PG_PORT must be a number")

    port = int(port_text)

    if port < 1 or port > 65535:
        raise UnsafeTestServerError("CARELOG_TEST_PG_PORT must be between 1 and 65535")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
    }


def read_application_target(env_file):
    # Reads where the application's own database is, from .env. Returns
    # None when the file does not exist, as in GitHub Actions. The
    # password is never read into the result.
    if not env_file.is_file():
        return None

    config = dotenv_values(env_file)

    return {
        "host": config.get("CARELOG_PG_HOST"),
        "port": config.get("CARELOG_PG_PORT"),
        "database": config.get("CARELOG_PG_DATABASE"),
        "user": config.get("CARELOG_PG_USER"),
    }


def normalize_host(host):
    # localhost, 127.0.0.1 and ::1 are the same machine
    if host is None:
        return None

    host = host.strip().lower()

    if host in LOCAL_HOST_NAMES:
        return "localhost"

    return host


def normalize_port(port):
    if port is None:
        return None

    port_text = str(port).strip()

    if not port_text.isdigit():
        return None

    return int(port_text)


def find_settings_problems(settings, application_target):
    # Checks the settings before any connection is made
    problems = []

    if settings["user"] in APPLICATION_ACCOUNTS:
        problems.append(
            f"CARELOG_TEST_PG_USER must not be {settings['user']}; use a separate test user"
        )

    if application_target is not None:
        if settings["user"] == application_target["user"]:
            problems.append("CARELOG_TEST_PG_USER is the application's database user")

        same_host = normalize_host(settings["host"]) == normalize_host(application_target["host"])
        same_port = normalize_port(settings["port"]) == normalize_port(application_target["port"])

        if same_host and same_port:
            problems.append(
                "CARELOG_TEST_PG_HOST and CARELOG_TEST_PG_PORT point to the "
                "application's database server in .env"
            )

    return problems


def collect_server_state(connection):
    # Reads the facts that the checks need from the server
    databases = []

    for row in connection.execute("SELECT datname FROM pg_database").fetchall():
        databases.append(row[0])

    roles = []

    for row in connection.execute("SELECT rolname FROM pg_roles").fetchall():
        roles.append(row[0])

    marker_row = connection.execute(
        "SELECT shobj_description(oid, 'pg_database') "
        "FROM pg_database WHERE datname = 'postgres'"
    ).fetchone()

    marker = None

    if marker_row is not None:
        marker = marker_row[0]

    # Tables of the postgres database itself, outside the system schemas.
    # A disposable server has none; application data might hide here.
    user_tables = connection.execute(
        "SELECT COUNT(*) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
        "AND n.nspname NOT LIKE 'pg_toast%'"
    ).fetchone()[0]

    return {
        "databases": databases,
        "roles": roles,
        "marker": marker,
        "user_tables": user_tables,
    }


def find_server_problems(server_state, application_target):
    problems = []

    if server_state["marker"] != TEST_SERVER_MARKER:
        problems.append("the server is not marked as a disposable test server")

    for database in server_state["databases"]:
        if database in DEFAULT_DATABASES:
            continue

        if database.startswith(TEST_DATABASE_PREFIX):
            continue

        problems.append(f"the server has a non-test database: {database}")

    if server_state["user_tables"] != 0:
        problems.append("the postgres database of the server has tables")

    forbidden_roles = list(APPLICATION_ACCOUNTS)

    if application_target is not None:
        if application_target["user"]:
            forbidden_roles.append(application_target["user"])

    for role in server_state["roles"]:
        if role in forbidden_roles:
            problems.append(f"the server has the CareLog account {role}")

    return problems


def verify_test_server(settings, application_target, connect):
    # Raises UnsafeTestServerError unless the test server passes every
    # check. connect(settings) opens a connection to the postgres
    # database of the test server; it is called only when the settings
    # themselves are safe.
    problems = find_settings_problems(settings, application_target)

    if problems:
        raise UnsafeTestServerError("; ".join(problems))

    connection = connect(settings)

    with connection:
        server_state = collect_server_state(connection)

    problems = find_server_problems(server_state, application_target)

    if problems:
        raise UnsafeTestServerError("; ".join(problems))
