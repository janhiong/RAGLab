import psycopg
from psycopg.rows import dict_row
from app.config import Settings

settings = Settings()


def connect():
    return psycopg.connect(settings.database_url, connect_timeout=3, row_factory=dict_row)
