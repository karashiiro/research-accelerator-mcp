"""
Research Accelerator Eval Harness

A test harness for evaluating the research accelerator MCP server
using Strands Agents SDK with z.ai API.

Usage:
    python -m eval.harness [--tasks T1.1 T2.1] [--runs 5]
"""

from .config import Config, get_config
from .model import ZAIModel
from .runner import EvalRunner, save_results_csv
from .tasks import Task, get_tasks

__all__ = [
    "get_config",
    "Config",
    "ZAIModel",
    "EvalRunner",
    "save_results_csv",
    "get_tasks",
    "Task",
]
