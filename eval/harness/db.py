"""
Database snapshot management for eval harness.

Handles clearing, snapshotting, and restoring the research database
to ensure consistent experimental conditions across runs.
"""

import shutil
import sqlite3
from pathlib import Path


class DatabaseManager:
    """
    Manages the research database for eval runs.

    Provides operations for:
    - Clearing the database (for cold runs)
    - Creating snapshots (after cold runs)
    - Restoring snapshots (for warm runs)
    - Loading ideal warm entries (hand-crafted descriptions)
    """

    def __init__(self, db_path: Path, snapshots_dir: Path) -> None:
        """
        Initialize the database manager.

        Args:
            db_path: Path to the research database file
            snapshots_dir: Directory for storing database snapshots
        """
        self.db_path = db_path
        self.snapshots_dir = snapshots_dir
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def clear_database(self) -> None:
        """
        Clear all entries from the database.

        Drops and recreates the FTS5 table to ensure a clean state.
        Also removes any WAL files.
        """
        # Close any existing connections by removing the file
        if self.db_path.exists():
            self.db_path.unlink()

        # Also remove WAL and SHM files if they exist
        wal_path = Path(str(self.db_path) + "-wal")
        shm_path = Path(str(self.db_path) + "-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()

        # Create fresh database with schema
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS research USING fts5(
                description,
                resource UNINDEXED
            )
        """)
        conn.commit()
        conn.close()

    def create_snapshot(self, task_id: str, run_id: int) -> Path:
        """
        Create a snapshot of the current database state.

        Args:
            task_id: Task identifier (e.g., "T1.1")
            run_id: Run number (1, 2, 3, ...)

        Returns:
            Path to the snapshot file
        """
        snapshot_name = f"cold_{task_id}_{run_id}.db"
        snapshot_path = self.snapshots_dir / snapshot_name

        # Checkpoint WAL to ensure all data is in main file
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        # Copy the database file
        shutil.copy2(self.db_path, snapshot_path)

        return snapshot_path

    def restore_snapshot(self, snapshot_path: Path) -> None:
        """
        Restore the database from a snapshot.

        Args:
            snapshot_path: Path to the snapshot file to restore
        """
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        # Clear existing database
        if self.db_path.exists():
            self.db_path.unlink()

        # Remove WAL files
        wal_path = Path(str(self.db_path) + "-wal")
        shm_path = Path(str(self.db_path) + "-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()

        # Copy snapshot to database path
        shutil.copy2(snapshot_path, self.db_path)

    def load_ideal_warm_entries(self, entries: list[dict[str, str]]) -> None:
        """
        Load hand-crafted entries for ideal-warm condition.

        Clears the database first, then inserts the provided entries.

        Args:
            entries: List of dicts with 'description' and 'resource' keys
        """
        # Start fresh
        self.clear_database()

        # Insert entries
        conn = sqlite3.connect(self.db_path)
        for entry in entries:
            conn.execute(
                "INSERT INTO research (description, resource) VALUES (?, ?)",
                (entry["description"], entry["resource"]),
            )
        conn.commit()
        conn.close()

    def get_entry_count(self) -> int:
        """Get the number of entries in the database."""
        if not self.db_path.exists():
            return 0

        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM research").fetchone()[0]
        conn.close()
        return count

    def get_all_entries(self) -> list[dict[str, str]]:
        """Get all entries from the database."""
        if not self.db_path.exists():
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT rowid, description, resource FROM research").fetchall()
        conn.close()

        return [
            {"rowid": row["rowid"], "description": row["description"], "resource": row["resource"]}
            for row in rows
        ]

    def list_snapshots(self) -> list[Path]:
        """List all available snapshots."""
        return list(self.snapshots_dir.glob("*.db"))
