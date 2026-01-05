# Research Index MCP Server

A minimal MCP server for indexing and searching research resources.

## Concept

Store *what something is about* (searchable) alongside *where/what it is* (actionable).

```sql
CREATE VIRTUAL TABLE research USING fts5(
    description,           -- Searchable text
    resource UNINDEXED     -- Stored but not searchable
);
```

---

## Tools

### `research_create`

Save a resource with a description so you can find it later by searching.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | yes | What this resource is about. Be descriptive — this is what you'll search against. |
| `resource` | string | yes | The resource: a URL, tool name, JSON, file path, or any identifier. |

**Returns** the ID of the saved entry.

**Example**
```json
{
  "description": "Vaswani et al. 2017 - Attention Is All You Need. Transformer architecture, self-attention, positional encoding.",
  "resource": "https://arxiv.org/abs/1706.03762"
}
```

---

### `research_search`

Find resources by searching their descriptions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Words to search for. Use quotes for exact phrases, `OR` between alternatives, `NOT` to exclude. |
| `limit` | number | no | Max results (default: 10). |

**Returns** matching entries with their descriptions and resources, best matches first.

**Query examples**

| Query | Finds |
|-------|-------|
| `attention transformer` | Entries containing both words |
| `transformer OR RNN` | Entries containing either word |
| `transformer NOT BERT` | Entries with transformer but not BERT |
| `"attention mechanism"` | Exact phrase |
| `transform*` | Prefix match: transformer, transformation, etc. |
| `NEAR(neural network, 5)` | "neural" and "network" within 5 words of each other |

You can combine these: `"deep learning" OR reinforcement NOT survey` finds deep learning or reinforcement learning entries, excluding surveys.

**Example**
```json
{
  "query": "attention transformer",
  "limit": 5
}
```

---

### `research_delete`

Remove an entry by its ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | number | yes | The ID of the entry to delete (returned by search or create). |

**Returns** whether the entry was found and deleted.

**Example**
```json
{
  "id": 42
}
```

---

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RESEARCH_DB_PATH` | `research.db` | Database file path. Use `:memory:` for temporary storage. |

---

## Implementation Sketch

```python
import sqlite3
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("research-index")

def get_db() -> sqlite3.Connection:
    path = os.environ.get("RESEARCH_DB_PATH", "research.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS research USING fts5(
            description,
            resource UNINDEXED
        )
    """)
    return conn

@mcp.tool()
def research_create(description: str, resource: str) -> str:
    """Save a resource with a description so you can find it later by searching."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO research (description, resource) VALUES (?, ?)",
        (description, resource)
    )
    conn.commit()
    return f"Saved with ID {cur.lastrowid}"

@mcp.tool()
def research_search(query: str, limit: int = 10) -> str:
    """Find resources by searching their descriptions.

    Query syntax:
    - `foo bar` — entries containing both words
    - `foo OR bar` — entries containing either word
    - `foo NOT bar` — entries with foo but not bar
    - `"exact phrase"` — exact phrase match
    - `prefix*` — prefix match (prefix, prefixed, etc.)
    - `NEAR(foo bar, 5)` — words within 5 words of each other

    Combine them: `"deep learning" OR reinforcement NOT survey`
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT rowid, description, resource FROM research WHERE research MATCH ? ORDER BY rank LIMIT ?",
        (query, limit)
    ).fetchall()
    if not rows:
        return "No results found."
    lines = []
    for r in rows:
        lines.append(f"[{r['rowid']}] {r['description']}\n    → {r['resource']}")
    return "\n\n".join(lines)

@mcp.tool()
def research_delete(id: int) -> str:
    """Remove an entry by its ID."""
    conn = get_db()
    cur = conn.execute("DELETE FROM research WHERE rowid = ?", (id,))
    conn.commit()
    if cur.rowcount > 0:
        return f"Deleted entry {id}."
    return f"No entry found with ID {id}."
```

Run with: `mcp run server.py`

---

## Testing Strategy

All tests use an in-memory database (`:memory:`) for speed and isolation. Each test function gets a fresh database — no state leaks between tests.

**What we test:**
- Each tool in isolation (create, search, delete)
- Search query syntax variations
- Edge cases (empty results, missing entries, invalid queries)

**What we don't test:**
- SQLite itself (trust the battle-tested library)
- MCP protocol handling (trust the SDK)

---

## Required Unit Tests

### `test_create_and_retrieve`
Create an entry, search for it, verify the description and resource match.

### `test_search_returns_best_matches_first`
Create multiple entries with varying relevance to a query, verify ordering.

### `test_search_no_results`
Search for something that doesn't exist, verify empty response.

### `test_search_with_phrases`
Create entries, search with `"exact phrase"`, verify only phrase matches return.

### `test_search_with_or`
Search with `foo OR bar`, verify entries with either term return.

### `test_search_with_not`
Search with `foo NOT bar`, verify exclusion works.

### `test_search_with_prefix`
Search with `transform*`, verify prefix matching works.

### `test_delete_existing`
Create an entry, delete it by ID, verify it's gone.

### `test_delete_nonexistent`
Delete an ID that doesn't exist, verify graceful "not found" response.

### `test_invalid_query_syntax`
Pass malformed query (e.g., unbalanced quotes), verify error handling.

---

## CI/CD (GitHub Actions)

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Lint
        run: ruff check .

      - name: Test
        run: pytest -v
```

**Dependencies** (`pyproject.toml` dev extras):
- `pytest` — test runner
- `ruff` — linting

**Branch protection** (recommended):
- Require CI to pass before merging
- Require PR reviews
