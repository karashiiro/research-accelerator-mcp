# Research Index MCP Server

A minimal MCP server for indexing and searching research resources.

Store *what something is about* (searchable) alongside *where/what it is* (actionable).

## Setup

```bash
# Install dependencies
uv sync

# Run the server (HTTP on port 9223)
uv run server.py
```

The server runs on `http://127.0.0.1:9223/mcp` using the Streamable HTTP transport.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RESEARCH_DB_PATH` | `research.db` | Database file path. Use `:memory:` for temporary storage. |
| `HOST` | `127.0.0.1` | Server bind address (configure in `server.py`). |
| `PORT` | `9223` | Server port (configure in `server.py`). |

## Tools

### `research_create`

Save a resource with a description so you can find it later by searching.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | yes | What this resource is about. Be descriptive - this is what you'll search against. |
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

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
uv run pytest -v

# Run linter
uv run ruff check .
```
