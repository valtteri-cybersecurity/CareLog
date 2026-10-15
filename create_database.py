
from pathlib import Path
from dotenv import dotenv_values
import pymysql

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"

config = dotenv_values(ENV_FILE)

CARELOG_HOST = config.get("CARELOG_HOST")
CARELOG_USER = config.get("CARELOG_USER")
CARELOG_PASSWORD = config.get("CARELOG_PASSWORD")
CARELOG_DATABASE = config.get("CARELOG_DATABASE")

CARELOG_ADMIN_USER = config.get("CARELOG_ADMIN_USER")
CARELOG_ADMIN_PASSWORD = config.get("CARELOG_ADMIN_PASSWORD")

if not all([
    CARELOG_HOST,
    CARELOG_USER,
    CARELOG_PASSWORD,
    CARELOG_DATABASE,
    CARELOG_ADMIN_USER,
    CARELOG_ADMIN_PASSWORD,
]):
    raise ValueError(
        f"CareLogin asetuksia puuttuu tiedostosta: {ENV_FILE}"
    )


def validate_identifier(value, name):
    if not value or not (
        value[0].isalpha() or value[0] == "_"
    ):
        raise ValueError(f"Virheellinen {name}: {value}")

    if not all(char.isalnum() or char == "_" for char in value):
        raise ValueError(f"Virheellinen {name}: {value}")


validate_identifier(CARELOG_USER, "käyttäjänimi")
validate_identifier(CARELOG_DATABASE, "tietokannan nimi")


def create_database():
    connection = pymysql.connect(
        host=CARELOG_HOST,
        user=CARELOG_ADMIN_USER,
        password=CARELOG_ADMIN_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE DATABASE IF NOT EXISTS `{CARELOG_DATABASE}`
                CHARACTER SET utf8mb4
                COLLATE utf8mb4_unicode_ci
                """
            )

            cursor.execute(
                """
                CREATE USER IF NOT EXISTS %s@'localhost'
                IDENTIFIED BY %s
                """,
                (CARELOG_USER, CARELOG_PASSWORD),
            )

            cursor.execute(
                """
                ALTER USER %s@'localhost'
                IDENTIFIED BY %s
                """,
                (CARELOG_USER, CARELOG_PASSWORD),
            )

            cursor.execute(
                f"""
                GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
                ON `{CARELOG_DATABASE}`.*
                TO %s@'localhost'
                """,
                (CARELOG_USER,),
            )

            cursor.execute(f"USE `{CARELOG_DATABASE}`")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS visits (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    event_date DATE NOT NULL,
                    start_time TIME NULL,
                    end_time TIME NULL,
                    expenses DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                    created_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    visit_id INT UNSIGNED NOT NULL,
                    entry_type ENUM(
                        'task',
                        'observation',
                        'follow_up',
                        'note'
                    ) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,

                    INDEX idx_entries_visit_id (visit_id),

                    CONSTRAINT fk_entries_visits
                        FOREIGN KEY (visit_id)
                        REFERENCES visits(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    content TEXT NOT NULL,
                    due_date DATE NULL,
                    status ENUM(
                        'planned',
                        'completed',
                        'cancelled'
                    ) NOT NULL DEFAULT 'planned',
                    completed_visit_id INT UNSIGNED NULL,
                    created_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    completed_at DATETIME NULL,

                    INDEX idx_tasks_status_due_date (
                        status,
                        due_date
                    ),

                    CONSTRAINT fk_tasks_completed_visit
                        FOREIGN KEY (completed_visit_id)
                        REFERENCES visits(id)
                        ON DELETE SET NULL
                ) ENGINE=InnoDB
            """)

        print(f"Tietokanta '{CARELOG_DATABASE}' on valmis.")
        print(f"MySQL-käyttäjä '{CARELOG_USER}' on määritetty.")
        print("Taulut luotu tai ne olivat jo olemassa:")
        print("- visits")
        print("- entries")
        print("- tasks")

    finally:
        connection.close()


if __name__ == "__main__":
    create_database()
