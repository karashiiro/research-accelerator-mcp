"""
Research Accelerator Eval Harness

A test harness for evaluating the research accelerator MCP server
using Strands Agents SDK.

Usage:
    python -m eval.harness [--tasks T1.1 T2.1] [--runs 5]
"""

from .config import Config, get_config
from .oauth import OAuthManager, get_or_create_oauth, interactive_login
from .runner import EvalRunner, save_results_csv
from .tasks import Task, get_tasks

__all__ = [
    "get_config",
    "Config",
    "OAuthManager",
    "get_or_create_oauth",
    "interactive_login",
    "EvalRunner",
    "save_results_csv",
    "get_tasks",
    "Task",
]
