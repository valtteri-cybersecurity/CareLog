from pathlib import Path

from dotenv import dotenv_values
import psycopg


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_DIR / ".env"


def load_postgres_config():
    if not ENV_FILE.is_file():
        raise FileNotFoundError("The .env file was not found")

    config = dotenv_values(ENV_FILE)

    required_settings = (
        "CARELOG_PG_HOST",
        "CARELOG_PG_PORT",
        "CARELOG_PG_DATABASE",
        "CARELOG_PG_USER",
        "CARELOG_PG_PASSWORD",
    )

    for setting in required_settings:
        if not config.get(setting):
            raise ValueError(f"Missing required setting: {setting}")

    return config


def get_postgres_connection(database=None, user=None, password=None):
    config = load_postgres_config()

    if database is None:
        database = config["CARELOG_PG_DATABASE"]

    if user is None:
        user = config["CARELOG_PG_USER"]

    if password is None:
        password = config["CARELOG_PG_PASSWORD"]

    connection = psycopg.connect(
        host=config["CARELOG_PG_HOST"],
        port=config["CARELOG_PG_PORT"],
        dbname=database,
        user=user,
        password=password,
        connect_timeout=10,
        options="-c timezone=UTC",
    )

    return connection
