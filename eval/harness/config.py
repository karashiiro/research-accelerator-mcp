"""
Eval harness configuration.

Loads settings from environment variables / .env file.
Authentication uses z.ai API key (ZAI_API_KEY environment variable).
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# .env file location (loaded lazily in load_config)
_harness_dir = Path(__file__).parent
_ENV_FILE = _harness_dir / ".env"
_dotenv_loaded = False


@dataclass
class Config:
    """Eval harness configuration."""

    # z.ai API configuration
    zai_api_key: str
    zai_base_url: str

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


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


def load_config() -> Config:
    """
    Load configuration from environment.

    Raises:
        ConfigError: If required configuration is missing.
    """
    global _dotenv_loaded

    # Load .env file lazily (only once)
    if not _dotenv_loaded:
        if _ENV_FILE.exists():
            load_dotenv(_ENV_FILE)
            logger.debug(f"Loaded environment from {_ENV_FILE}")
        _dotenv_loaded = True

    harness_dir = Path(__file__).parent

    # Load and validate z.ai API key (required)
    zai_api_key = os.getenv("ZAI_API_KEY", "")
    if not zai_api_key:
        raise ConfigError(
            "ZAI_API_KEY not set. Get an API key from z.ai and set it in environment "
            "or eval/harness/.env"
        )

    # z.ai base URL (optional, has default)
    zai_base_url = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/anthropic")

    # Load and validate Tavily API key
    tavily_api_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_api_key:
        logger.warning(
            "TAVILY_API_KEY not set - web search will not be available. "
            "Set it in environment or eval/harness/.env"
        )

    # Validate numeric configs
    try:
        mcp_port = int(os.getenv("EVAL_MCP_PORT", "9224"))
    except ValueError:
        raise ConfigError("EVAL_MCP_PORT must be a valid integer")

    try:
        runs_per_condition = int(os.getenv("EVAL_RUNS_PER_CONDITION", "5"))
        if runs_per_condition < 1:
            raise ValueError("must be positive")
    except ValueError as e:
        raise ConfigError(f"EVAL_RUNS_PER_CONDITION must be a positive integer: {e}")

    return Config(
        # z.ai API
        zai_api_key=zai_api_key,
        zai_base_url=zai_base_url,

        # Tools
        tavily_api_key=tavily_api_key,

        # MCP server (eval runs its own on port 9224 to avoid conflicts)
        mcp_port=mcp_port,
        mcp_host=os.getenv("EVAL_MCP_HOST", "127.0.0.1"),

        # Database (eval-specific, inside harness directory)
        db_path=harness_dir / os.getenv("EVAL_DB_PATH", "eval_research.db"),

        # Eval
        model_id=os.getenv("EVAL_MODEL_ID", "GLM-4.7"),
        runs_per_condition=runs_per_condition,
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
