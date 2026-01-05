# Contributing

Thanks for your interest in contributing to Research Index MCP Server!

## Development Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
# Clone the repo
git clone https://github.com/your-username/research-accelerator-mcp.git
cd research-accelerator-mcp

# Install dependencies (including dev dependencies)
uv sync --all-extras
```

## Running the Server

```bash
uv run server.py
```

The server runs on `http://127.0.0.1:9223/mcp` by default.

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RESEARCH_DB_PATH` | `research.db` | Database file path. Use `:memory:` for temporary storage. |
| `HOST` | `127.0.0.1` | Server bind address. |
| `PORT` | `9223` | Server port. |

## Architecture

This is a single-file MCP server (`server.py`) designed to be minimal and easy to understand.

### Components

```
server.py          # The entire server - MCP tools + database logic
tests/
  test_server.py   # Unit tests for all tools
```

### How It Works

1. **MCP Framework**: Uses [FastMCP](https://github.com/modelcontextprotocol/python-sdk) to expose tools that AI assistants can call. The server runs over Streamable HTTP transport via uvicorn.

2. **Database**: SQLite with [FTS5](https://www.sqlite.org/fts5.html) (full-text search) powers the search functionality. The schema is a single virtual table:
   ```sql
   CREATE VIRTUAL TABLE research USING fts5(
       description,           -- Searchable text
       resource UNINDEXED     -- Stored but not searchable
   )
   ```

3. **Tools**: The server exposes four MCP tools:
   - `research_create` - Add a new resource with a searchable description
   - `research_search` - Full-text search across descriptions (supports phrases, OR, NOT, prefix matching)
   - `research_delete` - Remove an entry by ID
   - `debug_research_query` - Run read-only SQL for debugging

### Design Decisions

- **Single file**: Keeps things simple and avoids over-engineering for a small tool
- **FTS5**: Provides powerful search syntax (phrases, boolean operators, prefix matching) with zero external dependencies
- **UNINDEXED resource**: The resource field is stored but not searchable, saving index space since you only search by description
- **WAL mode**: Write-ahead logging for better concurrent read performance (disabled for in-memory DBs)

## Code Quality

### Tests

Run the test suite with pytest:

```bash
uv run pytest -v
```

Tests use an in-memory SQLite database, so they won't affect your local `research.db`.

### Linting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting:

```bash
uv run ruff check .
```

To auto-fix issues:

```bash
uv run ruff check . --fix
```

### Code Style

- Python 3.11+
- Line length: 100 characters
- Follow existing patterns in the codebase

## Making Changes

1. Create a new branch for your changes
2. Make your changes
3. Run tests and linting to ensure everything passes:
   ```bash
   uv run ruff check . && uv run pytest -v
   ```
4. Commit your changes with a clear message
5. Open a pull request

## CI

All pull requests run through GitHub Actions CI which:
- Lints the code with Ruff
- Runs the test suite with pytest

Make sure both pass before requesting review.

## License

This project is released into the public domain under [The Unlicense](https://unlicense.org). By contributing, you agree to release your contributions into the public domain as well.
