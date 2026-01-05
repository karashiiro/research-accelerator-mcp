"""Research Index MCP Server.

A minimal MCP server for indexing and searching research resources.
"""

import os
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("research-index")

# Cache the database connection (important for in-memory databases)
_db_connection: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    """Get a database connection, creating the table if needed.

    The connection is cached to ensure in-memory databases work correctly
    (each SQLite in-memory connection is a separate database).
    """
    global _db_connection

    if _db_connection is not None:
        return _db_connection

    path = os.environ.get("RESEARCH_DB_PATH", "research.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL mode doesn't work with in-memory databases, so only set it for file-based DBs
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS research USING fts5(
            description,
            resource UNINDEXED
        )
    """)
    _db_connection = conn
    return conn


def reset_db() -> None:
    """Reset the database connection. Used for testing."""
    global _db_connection
    if _db_connection is not None:
        _db_connection.close()
        _db_connection = None


@mcp.tool()
def research_create(description: str, resource: str) -> str:
    """Save a resource with a description so you can find it later by searching.

    Args:
        description: What this resource is about. Be descriptive - this is what
            you'll search against.
        resource: The resource: a URL, tool name, JSON, file path, or any identifier.

    Returns:
        The ID of the saved entry, or the existing ID if an exact duplicate exists.
    """
    conn = get_db()

    # Check for exact duplicate (same description AND same resource)
    existing = conn.execute(
        "SELECT rowid FROM research WHERE description = ? AND resource = ?",
        (description, resource),
    ).fetchone()

    if existing:
        return f"Already exists with ID {existing['rowid']}"

    cur = conn.execute(
        "INSERT INTO research (description, resource) VALUES (?, ?)",
        (description, resource),
    )
    conn.commit()
    return f"Saved with ID {cur.lastrowid}"


@mcp.tool()
def research_search(query: str, limit: int = 10) -> str:
    """Find resources by searching their descriptions.

    Query syntax:
    - `foo bar` - entries containing both words
    - `foo OR bar` - entries containing either word
    - `foo NOT bar` - entries with foo but not bar
    - `"exact phrase"` - exact phrase match
    - `prefix*` - prefix match (prefix, prefixed, etc.)
    - `NEAR(foo bar, 5)` - words within 5 words of each other

    Combine them: `"deep learning" OR reinforcement NOT survey`

    Args:
        query: Words to search for. Use quotes for exact phrases, OR between
            alternatives, NOT to exclude.
        limit: Max results (default: 10).

    Returns:
        Matching entries with their descriptions and resources, best matches first.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT rowid, description, resource FROM research "
        "WHERE research MATCH ? ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    if not rows:
        return "No results found."
    lines = []
    for r in rows:
        lines.append(f"[{r['rowid']}] {r['description']}\n    -> {r['resource']}")
    return "\n\n".join(lines)


@mcp.tool()
def research_delete(id: int) -> str:
    """Remove an entry by its ID.

    Args:
        id: The ID of the entry to delete (returned by search or create).

    Returns:
        Whether the entry was found and deleted.
    """
    conn = get_db()
    cur = conn.execute("DELETE FROM research WHERE rowid = ?", (id,))
    conn.commit()
    if cur.rowcount > 0:
        return f"Deleted entry {id}."
    return f"No entry found with ID {id}."


@mcp.tool()
def debug_research_query(sql: str) -> str:
    """Run a read-only SQL query against the research database for debugging.

    The database has an FTS5 virtual table called 'research' with columns:
    - rowid: Auto-generated integer ID
    - description: Searchable text describing the resource
    - resource: The URL, tool name, or identifier (UNINDEXED)

    Args:
        sql: A SELECT query to run. Only SELECT statements are allowed.

    Returns:
        Query results as formatted text, or an error message.
    """
    # Only allow SELECT queries for safety
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return "Error: Only SELECT queries are allowed for debugging."

    conn = get_db()
    try:
        rows = conn.execute(sql).fetchall()
        if not rows:
            return "No results."
        # Format results
        lines = []
        for row in rows:
            if hasattr(row, "keys"):
                # sqlite3.Row object
                cols = row.keys()
                parts = [f"{col}={row[col]!r}" for col in cols]
                lines.append(" | ".join(parts))
            else:
                # Tuple result
                lines.append(str(row))
        return "\n".join(lines)
    except sqlite3.Error as e:
        return f"SQL Error: {e}"


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "9223"))
    uvicorn.run(mcp.streamable_http_app(), host=host, port=port)
