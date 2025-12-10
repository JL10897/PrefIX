# check_mysql_rw.py
import os
import mysql.connector
from dotenv import load_dotenv
# load_dotenv()
load_dotenv(dotenv_path="/Users/JL/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/.env")

cfg = {
    "user": os.environ["DATABASE_USER"],
    "password": os.environ["DATABASE_PASSWORD"],
    "host": os.environ.get("DATABASE_HOST", "127.0.0.1"),
    "database": os.environ["DATABASE_NAME"],
    "port": int(os.environ.get("DATABASE_PORT", "3306")),
    "autocommit": False,
}

conn = mysql.connector.connect(**cfg)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS goex_tmp_probe(id INT PRIMARY KEY, note VARCHAR(32))")
cur.execute("INSERT INTO goex_tmp_probe (id, note) VALUES (99999, 'probe')")
conn.rollback()  # 清理探针数据
cur.execute("DROP TABLE IF EXISTS goex_tmp_probe")
conn.commit()
cur.close()
conn.close()
print("RW probe completed with rollback.")
