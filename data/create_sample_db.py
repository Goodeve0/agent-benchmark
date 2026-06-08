"""创建示例数据库（Sakila 风格的电影租赁数据库）。

用于 DataAnalystAdapter 的真实数据库查询评测。

运行方式:
    python data/create_sample_db.py

生成文件:
    data/sakila.db (SQLite 数据库)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "sakila.db"


def create_database() -> None:
    """创建示例数据库。"""
    if DB_PATH.exists():
        print(f"数据库已存在: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 创建表
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS actor (
            actor_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS film (
            film_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            release_year INTEGER,
            language_id INTEGER,
            rental_duration INTEGER DEFAULT 3,
            rental_rate REAL DEFAULT 4.99,
            length INTEGER,
            replacement_cost REAL DEFAULT 19.99,
            rating TEXT DEFAULT 'G',
            special_features TEXT
        );

        CREATE TABLE IF NOT EXISTS category (
            category_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS film_category (
            film_id INTEGER,
            category_id INTEGER,
            PRIMARY KEY (film_id, category_id)
        );

        CREATE TABLE IF NOT EXISTS customer (
            customer_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            active INTEGER DEFAULT 1,
            create_date TEXT DEFAULT CURRENT_DATE
        );

        CREATE TABLE IF NOT EXISTS rental (
            rental_id INTEGER PRIMARY KEY,
            rental_date TEXT NOT NULL,
            inventory_id INTEGER,
            customer_id INTEGER,
            return_date TEXT,
            staff_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS payment (
            payment_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            rental_id INTEGER,
            amount REAL NOT NULL,
            payment_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS staff (
            staff_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            active INTEGER DEFAULT 1
        );
    """)

    # 插入示例数据
    cursor.executemany(
        "INSERT INTO actor (actor_id, first_name, last_name) VALUES (?, ?, ?)",
        [
            (1, "PENELOPE", "GUINESS"), (2, "NICK", "WAHLBERG"), (3, "ED", "CHASE"),
            (4, "JENNIFER", "DAVIS"), (5, "JOHNNY", "LOLLOBRIGIDA"),
            (6, "BETTE", "NICHOLSON"), (7, "GRACE", "MOSTEL"),
            (8, "MATTHEW", "JOHANSSON"), (9, "JOE", "SWANK"),
            (10, "CHRISTIAN", "GABLE"),
        ],
    )

    cursor.executemany(
        "INSERT INTO category (category_id, name) VALUES (?, ?)",
        [
            (1, "Action"), (2, "Animation"), (3, "Children"),
            (4, "Classics"), (5, "Comedy"), (6, "Documentary"),
            (7, "Drama"), (8, "Family"), (9, "Foreign"),
            (10, "Games"), (11, "Horror"), (12, "Music"),
            (13, "New"), (14, "Sci-Fi"), (15, "Sports"), (16, "Travel"),
        ],
    )

    films = [
        (1, "ACADEMY DINOSAUR", "A Epic Drama of a Feminist And a Mad Scientist", 2006, 1, 3, 0.99, 86, 20.99, "PG", "Deleted Scenes"),
        (2, "ACE GOLDFINGER", "A Astounding Epistle of a Database Administrator And a Explorer", 2006, 1, 3, 4.99, 48, 12.99, "G", "Trailers"),
        (3, "ADAPTATION HOLES", "A Astounding Reflection of a Lumberjack And a Car", 2006, 1, 7, 2.99, 50, 18.99, "NC-17", "Trailers,Deleted Scenes"),
        (4, "AFFAIR PREJUDICE", "A Fanciful Documentary of a Frisbee And a Lumberjack", 2006, 1, 5, 2.99, 117, 26.99, "G", "Commentaries"),
        (5, "AFRICAN EGG", "A Fast-Paced Documentary of a Pastry Chef And a Dentist", 2006, 1, 6, 2.99, 130, 22.99, "G", "Deleted Scenes"),
        (6, "AGENT TRUMAN", "A Intrepid Panorama of a Dentist And a Crocodile", 2006, 1, 3, 2.99, 169, 17.99, "PG", "Deleted Scenes,Behind the Scenes"),
        (7, "AIRPLANE SPRING", "A Touching Saga of a Hunter And a Butler", 2006, 1, 7, 4.99, 90, 16.99, "PG-13", "Trailers"),
        (8, "AIRPORT POLLOCK", "A Epic Tale of a Moose And a Girl", 2006, 1, 3, 4.99, 54, 21.99, "R", "Trailers"),
        (9, "ALABAMA DEVIL", "A Thoughtful Panorama of a Database Administrator And a Butler", 2006, 1, 3, 2.99, 101, 18.99, "PG-13", "Commentaries,Deleted Scenes"),
        (10, "ALADDIN CALENDAR", "A Action-Packed Tale of a Man And a Lumberjack", 2006, 1, 6, 4.99, 63, 24.99, "NC-17", "Trailers,Behind the Scenes"),
    ]
    cursor.executemany(
        "INSERT INTO film (film_id, title, description, release_year, language_id, rental_duration, rental_rate, length, replacement_cost, rating, special_features) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        films,
    )

    cursor.executemany(
        "INSERT INTO film_category (film_id, category_id) VALUES (?, ?)",
        [(1, 6), (2, 11), (3, 7), (4, 5), (5, 6),
         (6, 1), (7, 5), (8, 9), (9, 1), (10, 16)],
    )

    cursor.executemany(
        "INSERT INTO customer (customer_id, first_name, last_name, email, active, create_date) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "MARY", "SMITH", "MARY.SMITH@sakilacustomer.org", 1, "2024-01-01"),
            (2, "PATRICIA", "JOHNSON", "PATRICIA.JOHNSON@sakilacustomer.org", 1, "2024-01-02"),
            (3, "LINDA", "WILLIAMS", "LINDA.WILLIAMS@sakilacustomer.org", 1, "2024-01-03"),
            (4, "BARBARA", "JONES", "BARBARA.JONES@sakilacustomer.org", 0, "2024-01-04"),
            (5, "ELIZABETH", "BROWN", "ELIZABETH.BROWN@sakilacustomer.org", 1, "2024-01-05"),
        ],
    )

    cursor.executemany(
        "INSERT INTO staff (staff_id, first_name, last_name, email, active) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Mike", "Hillyer", "Mike.Hillyer@sakilastaff.org", 1),
            (2, "Jon", "Stephens", "Jon.Stephens@sakilastaff.org", 1),
        ],
    )

    # 插入一些租赁和支付记录
    import random
    random.seed(42)
    rental_id = 1
    payment_id = 1
    for cust_id in range(1, 6):
        for _ in range(5):
            film_id = random.randint(1, 10)
            rental_date = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
            return_days = random.randint(1, 14)
            return_date = f"2024-{random.randint(1,12):02d}-{min(random.randint(1,28), 28):02d}"
            amount = round(random.uniform(0.99, 9.99), 2)
            staff_id = random.choice([1, 2])

            cursor.execute(
                "INSERT INTO rental (rental_id, rental_date, inventory_id, customer_id, return_date, staff_id) VALUES (?, ?, ?, ?, ?, ?)",
                (rental_id, rental_date, film_id, cust_id, return_date, staff_id),
            )
            cursor.execute(
                "INSERT INTO payment (payment_id, customer_id, rental_id, amount, payment_date) VALUES (?, ?, ?, ?, ?)",
                (payment_id, cust_id, rental_id, amount, rental_date),
            )
            rental_id += 1
            payment_id += 1

    conn.commit()
    conn.close()
    print(f"示例数据库已创建: {DB_PATH}")
    print("包含以下表: actor, film, category, film_category, customer, rental, payment, staff")


if __name__ == "__main__":
    create_database()
