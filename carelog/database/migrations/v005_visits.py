def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE visits (
        id INT AUTO_INCREMENT PRIMARY KEY,
        client_id INT NOT NULL,
        service_id INT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'planned',
        priority TINYINT NOT NULL DEFAULT 2,
        planned_week DATE NULL,
        planned_at DATETIME NULL,
        started_at DATETIME NULL,
        ended_at DATETIME NULL,
        description TEXT NULL,
        distance_km DECIMAL(10, 2) NULL,
        price DECIMAL(10, 2) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        FOREIGN KEY (client_id) REFERENCES clients(id),
        FOREIGN KEY (service_id) REFERENCES services(id)
        ) ENGINE=InnoDB
""")