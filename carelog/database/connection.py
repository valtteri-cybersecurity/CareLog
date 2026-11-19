
from pathlib import Path

from dotenv import dotenv_values
import pymysql


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_DIR / ".env"

SQL_MODE = (
    "ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,"
    "NO_ZERO_IN_DATE,NO_ZERO_DATE,"
    "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"
)
TIME_ZONE = "+00:00"


def load_config():
    if not ENV_FILE.is_file():
        raise FileNotFoundError("The .env file was not found")

    config = dotenv_values(ENV_FILE)

    required_settings = (
        "CARELOG_HOST",
        "CARELOG_DATABASE",
        "CARELOG_USER",
        "CARELOG_PASSWORD",
    )

    for setting in required_settings:
        if not config.get(setting):
            raise ValueError(f"Missing required setting: {setting}")

    return config


def configure_session(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SET SESSION sql_mode = %s",
            (SQL_MODE,)
        )
        cursor.execute(
            "SET SESSION time_zone = %s",
            (TIME_ZONE,)
        )


def get_connection(database=None, user=None, password=None):
    config = load_config()

    if database is None:
        database = config["CARELOG_DATABASE"]

    if user is None:
        user = config["CARELOG_USER"]

    if password is None:
        password = config["CARELOG_PASSWORD"]

    connection = pymysql.connect(
        host=config["CARELOG_HOST"],
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        connect_timeout=10,
    )

    try:
        configure_session(connection)
    except Exception:
        connection.close()
        raise

    return connection


def check_database_connection():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            database_name = cursor.fetchone()[0]
            return database_name

    finally:
        connection.close()
