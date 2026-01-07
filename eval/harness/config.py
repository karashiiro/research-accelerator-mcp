"""
Eval harness configuration.

Loads settings from environment variables / .env file.
Authentication is handled interactively via OAuth flow, not stored in config.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from harness directory
_harness_dir = Path(__file__).parent
load_dotenv(_harness_dir / ".env")


@dataclass
class Config:
    """Eval harness configuration."""

    # Tool API keys
    tavily_api_key: str

    # MCP server (eval harness runs its own server)
    mcp_port: int
    mcp_host: str

    # Database (eval-specific, inside harness directory)
    db_path: Path

    # Eval settings
    model_id: str
    runs_per_condition: int
    results_dir: Path
    snapshots_dir: Path
    traces_dir: Path

    @property
    def mcp_url(self) -> str:
        """Get the MCP server URL."""
        return f"http://{self.mcp_host}:{self.mcp_port}/mcp"


def load_config() -> Config:
    """Load configuration from environment."""

    harness_dir = Path(__file__).parent

    return Config(
        # Tools
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),

        # MCP server (eval runs its own on port 9224 to avoid conflicts)
        mcp_port=int(os.getenv("EVAL_MCP_PORT", "9224")),
        mcp_host=os.getenv("EVAL_MCP_HOST", "127.0.0.1"),

        # Database (eval-specific, inside harness directory)
        db_path=harness_dir / os.getenv("EVAL_DB_PATH", "eval_research.db"),

        # Eval
        model_id=os.getenv("EVAL_MODEL_ID", "claude-sonnet-4-20250514"),
        runs_per_condition=int(os.getenv("EVAL_RUNS_PER_CONDITION", "5")),
        results_dir=harness_dir / os.getenv("EVAL_RESULTS_DIR", "./results"),
        snapshots_dir=harness_dir / os.getenv("EVAL_SNAPSHOTS_DIR", "./snapshots"),
        traces_dir=harness_dir / os.getenv("EVAL_TRACES_DIR", "./traces"),
    )


# Singleton config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the singleton config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
