import os
import mysql.connector  # 来自 mysql-connector-python
from dotenv import load_dotenv

load_dotenv()

cfg = {
    "user": os.environ["DATABASE_USER"],
    "password": os.environ["DATABASE_PASSWORD"],
    "host": os.environ.get("DATABASE_HOST", "127.0.0.1"),
    "database": os.environ["DATABASE_NAME"],
    "port": int(os.environ.get("DATABASE_PORT", "3306")),
}

conn = mysql.connector.connect(**cfg)
print("Server version:", conn.get_server_info())
conn.ping(reconnect=True, attempts=3, delay=2)
with conn.cursor() as cur:
    cur.execute("SELECT 1")
    print("SELECT 1 ->", cur.fetchone()[0])
conn.close()