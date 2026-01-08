"""
Database snapshot management for eval harness.

Handles clearing, snapshotting, and restoring the research database
to ensure consistent experimental conditions across runs.
"""

import logging
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def _get_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Context manager for database connections."""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _remove_wal_files(db_path: Path) -> None:
    """Remove WAL and SHM files if they exist."""
    wal_path = db_path.with_suffix(db_path.suffix + "-wal")
    shm_path = db_path.with_suffix(db_path.suffix + "-shm")

    for path in [wal_path, shm_path]:
        if path.exists():
            try:
                path.unlink()
            except OSError as e:
                logger.warning(f"Failed to remove {path}: {e}")


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

        Tries to delete the file, but if locked (Windows), drops and recreates the table.
        Also removes any WAL files.
        """
        file_deleted = False

        # Try to remove existing database and WAL files
        if self.db_path.exists():
            try:
                self.db_path.unlink()
                file_deleted = True
            except OSError as e:
                logger.warning(f"Database file locked, will truncate instead: {e}")

        if file_deleted:
            _remove_wal_files(self.db_path)

        # Create/recreate database with schema
        with _get_connection(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")

            if not file_deleted:
                # File was locked - drop and recreate the table to clear data
                conn.execute("DROP TABLE IF EXISTS research")

            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS research USING fts5(
                    description,
                    resource UNINDEXED
                )
            """)
            conn.commit()

        logger.debug(f"Database cleared: {self.db_path}")

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
        with _get_connection(self.db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        # Copy the database file (after checkpoint, WAL should be empty)
        shutil.copy2(self.db_path, snapshot_path)

        logger.debug(f"Created snapshot: {snapshot_path}")
        return snapshot_path

    def restore_snapshot(self, snapshot_path: Path) -> None:
        """
        Restore the database from a snapshot.

        Args:
            snapshot_path: Path to the snapshot file to restore
        """
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        # Try to remove existing database and WAL files
        file_deleted = False
        if self.db_path.exists():
            try:
                self.db_path.unlink()
                file_deleted = True
            except OSError as e:
                logger.warning(f"Database file locked, will copy contents instead: {e}")

        if file_deleted:
            _remove_wal_files(self.db_path)
            # Copy snapshot to database path
            shutil.copy2(snapshot_path, self.db_path)
        else:
            # File locked - copy contents via SQL instead
            with _get_connection(self.db_path) as conn:
                conn.execute("DROP TABLE IF EXISTS research")
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS research USING fts5(
                        description,
                        resource UNINDEXED
                    )
                """)

                # Attach snapshot and copy data
                conn.execute(f"ATTACH DATABASE ? AS snapshot", (str(snapshot_path),))
                conn.execute("INSERT INTO research SELECT * FROM snapshot.research")
                conn.execute("DETACH DATABASE snapshot")
                conn.commit()

        logger.debug(f"Restored snapshot: {snapshot_path}")

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
        with _get_connection(self.db_path) as conn:
            for entry in entries:
                try:
                    conn.execute(
                        "INSERT INTO research (description, resource) VALUES (?, ?)",
                        (entry["description"], entry["resource"]),
                    )
                except sqlite3.Error as e:
                    logger.error(f"Failed to insert entry: {e}")
            conn.commit()

        logger.debug(f"Loaded {len(entries)} ideal warm entries")

    def get_entry_count(self) -> int:
        """Get the number of entries in the database."""
        if not self.db_path.exists():
            return 0

        with _get_connection(self.db_path) as conn:
            result = conn.execute("SELECT COUNT(*) FROM research").fetchone()
            return result[0] if result else 0

    def get_all_entries(self) -> list[dict[str, str | int]]:
        """Get all entries from the database."""
        if not self.db_path.exists():
            return []

        with _get_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT rowid, description, resource FROM research").fetchall()

        return [
            {"rowid": row["rowid"], "description": row["description"], "resource": row["resource"]}
            for row in rows
        ]

    def list_snapshots(self) -> list[Path]:
        """List all available snapshots."""
        return list(self.snapshots_dir.glob("*.db"))
