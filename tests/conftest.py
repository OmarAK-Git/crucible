import os
import tempfile
from pathlib import Path
import pytest
from backend import db

@pytest.fixture(scope="session", autouse=True)
def test_db_env():
    # Create a temporary file for the database
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_crucible.db"
    
    # Set the environment variable for db.py
    os.environ["CRUCIBLE_DB_PATH"] = str(db_path)
    
    yield
    
    # Clean up
    temp_dir.cleanup()

@pytest.fixture(autouse=True)
def clean_db():
    # Initialize the database (creates tables)
    db.init_db()
    
    # Clean all tables before each test to ensure isolation
    conn = db.get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM scores;")
            conn.execute("DELETE FROM proposals;")
            conn.execute("DELETE FROM turns;")
            conn.execute("DELETE FROM rounds;")
            conn.execute("DELETE FROM sessions;")
    finally:
        conn.close()
