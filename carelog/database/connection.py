from pathlib import Path

from dotenv import dotenv_values
import pymysql

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_DIR / ".env"

def load_config():
    if not ENV_FILE.is_file():
        raise FileNotFoundError("The .env file was not found")

    config = dotenv_values(ENV_FILE)

    required_settings = (
        "CARELOG_HOST",
        "CARELOG_DATABASE",
        "CARELOG_USER",
        "CARELOG_PASSWORD"
    )

    for setting in required_settings:
        if not config.get(setting):
            raise ValueError(f"Missing required setting: {setting}")

    return config

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
