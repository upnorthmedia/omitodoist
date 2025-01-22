import sqlite3
from pathlib import Path
import os

# Get the directory containing this file
DB_DIR = Path(__file__).parent
DB_FILE = DB_DIR / "todoist_keys.db"

def init_db():
    """Initialize the database and create tables if they don't exist"""
    # Create db directory if it doesn't exist
    os.makedirs(DB_DIR, exist_ok=True)
    
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    # Create table for storing API keys
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS todoist_keys (
        uid TEXT PRIMARY KEY,
        api_key TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

def store_api_key(uid: str, api_key: str) -> bool:
    """Store or update a Todoist API key for a user"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO todoist_keys (uid, api_key)
        VALUES (?, ?)
        ''', (uid, api_key))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Error storing API key: {e}")
        return False
    finally:
        conn.close()

def get_api_key(uid: str) -> str | None:
    """Retrieve a Todoist API key for a user"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT api_key FROM todoist_keys WHERE uid = ?', (uid,))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        print(f"Error retrieving API key: {e}")
        return None
    finally:
        conn.close()

# Initialize the database when this module is imported
init_db() 