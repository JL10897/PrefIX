import os
import mysql.connector
from dotenv import load_dotenv
load_dotenv(dotenv_path="/Users/JL/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/.env")

conn = mysql.connector.connect(
    user=os.environ["DATABASE_USER"],
    password=os.environ["DATABASE_PASSWORD"],
    host=os.environ.get("DATABASE_HOST", "127.0.0.1"),
    database=os.environ["DATABASE_NAME"])
