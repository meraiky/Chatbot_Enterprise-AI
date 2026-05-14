"""
backup.py — Backup utility for AIAgentChatbot.

This script creates a comprehensive backup of all persistent data:
- PostgreSQL database (via pg_dump)
- ChromaDB vector store
- BM25 index cache
- SQLite usage database
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
BACKUP_DIR = Path("backups")
DATA_DIR = Path("data")
DB_CONTAINER_NAME = "aiagent_db"
DB_USER = "postgres"
DB_NAME = "aiagent_db"

def run_command(cmd: list[str]) -> str:
    """Run a shell command and return its output."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(cmd)}: {e.stderr}")
        raise

def backup_postgres():
    """Backup PostgreSQL database using pg_dump via Docker."""
    print("Backing up PostgreSQL...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"postgres_backup_{timestamp}.sql"
    
    # Use docker exec to run pg_dump and stream output to a local file
    cmd = [
        "docker", "exec", DB_CONTAINER_NAME,
        "pg_dump", "-U", DB_USER, "-d", DB_NAME
    ]
    
    with open(backup_file, "w") as f:
        subprocess.run(cmd, stdout=f, check=True)
    
    print(f"PostgreSQL backup saved to {backup_file}")

def backup_files():
    """Backup file-based data stores."""
    print("Backing up file-based data...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = BACKUP_DIR / f"files_backup_{timestamp}"
    archive_path = shutil.make_archive(
        str(archive_name), 'gzip', root_dir=DATA_DIR
    )
    print(f"Files backup saved to {archive_path}")

def main():
    """Main backup execution flow."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        backup_postgres()
        backup_files()
        print("\n✅ Full system backup completed successfully!")
    except Exception as e:
        print(f"\n❌ Backup failed: {e}")

if __name__ == "__main__":
    main()
