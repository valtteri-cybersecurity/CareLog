import pytest

from carelog.database import postgres_connection


def test_load_config_missing_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"

    monkeypatch.setattr(
        postgres_connection,
        "ENV_FILE",
        env_file
    )

    with pytest.raises(FileNotFoundError):
        postgres_connection.load_postgres_config()


def test_load_config_missing_setting(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"

    env_file.write_text(
        "CARELOG_PG_HOST=127.0.0.1\n"
        "CARELOG_PG_PORT=5433\n"
        "CARELOG_PG_DATABASE=carelog\n"
        "CARELOG_PG_USER=carelog_app\n"
    )

    monkeypatch.setattr(
        postgres_connection,
        "ENV_FILE",
        env_file
    )

    with pytest.raises(ValueError, match="CARELOG_PG_PASSWORD"):
        postgres_connection.load_postgres_config()


def test_get_postgres_connection(monkeypatch):
    config = {
        "CARELOG_PG_HOST": "127.0.0.1",
        "CARELOG_PG_PORT": "5433",
        "CARELOG_PG_DATABASE": "carelog",
        "CARELOG_PG_USER": "carelog_app",
        "CARELOG_PG_PASSWORD": "test_password",
    }

    received_settings = {}

    def fake_load_config():
        return config

    def fake_connect(**kwargs):
        received_settings.update(kwargs)
        return "test_connection"

    monkeypatch.setattr(
        postgres_connection,
        "load_postgres_config",
        fake_load_config
    )

    monkeypatch.setattr(
        postgres_connection.psycopg,
        "connect",
        fake_connect
    )

    connection = postgres_connection.get_postgres_connection()

    assert connection == "test_connection"
    assert received_settings["host"] == "127.0.0.1"
    assert received_settings["port"] == "5433"
    assert received_settings["dbname"] == "carelog"
    assert received_settings["user"] == "carelog_app"
    assert received_settings["password"] == "test_password"
    assert received_settings["connect_timeout"] == 10
    assert received_settings["options"] == "-c timezone=UTC"


def test_get_postgres_connection_with_overrides(monkeypatch):
    config = {
        "CARELOG_PG_HOST": "127.0.0.1",
        "CARELOG_PG_PORT": "5433",
        "CARELOG_PG_DATABASE": "carelog",
        "CARELOG_PG_USER": "carelog_app",
        "CARELOG_PG_PASSWORD": "app_password",
    }

    received_settings = {}

    def fake_load_config():
        return config

    def fake_connect(**kwargs):
        received_settings.update(kwargs)
        return "test_connection"

    monkeypatch.setattr(
        postgres_connection,
        "load_postgres_config",
        fake_load_config
    )

    monkeypatch.setattr(
        postgres_connection.psycopg,
        "connect",
        fake_connect
    )

    connection = postgres_connection.get_postgres_connection(
        database="carelog_test",
        user="carelog_migrator",
        password="migrator_password"
    )

    assert connection == "test_connection"
    assert received_settings["dbname"] == "carelog_test"
    assert received_settings["user"] == "carelog_migrator"
    assert received_settings["password"] == "migrator_password"
