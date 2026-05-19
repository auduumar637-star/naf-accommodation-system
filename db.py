import os
import psycopg2


def get_connection():

    try:

        DATABASE_URL = os.getenv("DATABASE_URL")

        # RENDER / ONLINE DATABASE
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)

        # LOCAL DATABASE
        else:
            conn = psycopg2.connect(
                host="localhost",
                database="naf_accommodation_v2",
                user="postgres",
                password="1234"
            )

        return conn

    except Exception as e:
        print("Database connection error:", e)
        return None