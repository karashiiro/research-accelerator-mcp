"""
Task definitions loader.

Loads structured task definitions from eval/tasks.yaml.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

logger = logging.getLogger(__name__)


class TaskLoadError(Exception):
    """Exception raised when task loading fails."""

    pass


# Required fields for each task in the YAML
REQUIRED_TASK_FIELDS = {"family", "type", "prompt", "ground_truth", "success_threshold"}

TaskType = Literal["primary", "related", "unrelated_control"]


@dataclass
class GroundTruthItem:
    """A single ground truth resource to find."""

    paper: str
    matchers: list[str]


@dataclass
class WarmIndexEntry:
    """An entry for pre-warming the index."""

    description: str
    resource: str


@dataclass
class Task:
    """A single evaluation task."""

    task_id: str
    family: str
    task_type: TaskType
    prompt: str
    ground_truth: list[GroundTruthItem]
    success_threshold: int
    warm_index_entries: list[WarmIndexEntry] = field(default_factory=list)
    related_task: str | None = None
    primary_task: str | None = None

    def get_matchers_for_metrics(self) -> list[dict[str, list[str]]]:
        """Convert ground truth to format expected by TaskMatcher."""
        return [
            {"paper": gt.paper, "matchers": gt.matchers}
            for gt in self.ground_truth
        ]


def _validate_task(task_id: str, task_data: dict) -> list[str]:
    """
    Validate a task definition has required fields.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Check required top-level fields
    missing = REQUIRED_TASK_FIELDS - set(task_data.keys())
    if missing:
        errors.append(f"Task {task_id}: missing required fields: {missing}")

    # Validate ground_truth structure
    ground_truth = task_data.get("ground_truth", [])
    if not isinstance(ground_truth, list):
        errors.append(f"Task {task_id}: ground_truth must be a list")
    else:
        for i, gt in enumerate(ground_truth):
            if not isinstance(gt, dict):
                errors.append(f"Task {task_id}: ground_truth[{i}] must be a dict")
            elif "paper" not in gt or "matchers" not in gt:
                errors.append(f"Task {task_id}: ground_truth[{i}] missing 'paper' or 'matchers'")
            elif not isinstance(gt.get("matchers"), list):
                errors.append(f"Task {task_id}: ground_truth[{i}].matchers must be a list")

    # Validate warm_index_entries structure if present
    warm_entries = task_data.get("warm_index_entries", [])
    if not isinstance(warm_entries, list):
        errors.append(f"Task {task_id}: warm_index_entries must be a list")
    else:
        for i, entry in enumerate(warm_entries):
            if not isinstance(entry, dict):
                errors.append(f"Task {task_id}: warm_index_entries[{i}] must be a dict")
            elif "description" not in entry or "resource" not in entry:
                msg = f"Task {task_id}: warm_index_entries[{i}] missing fields"
                errors.append(msg)

    return errors


def load_tasks(yaml_path: Path | None = None) -> dict[str, Task]:
    """
    Load task definitions from YAML file.

    Args:
        yaml_path: Path to tasks.yaml. Defaults to eval/tasks.yaml.

    Returns:
        Dictionary mapping task_id to Task objects.

    Raises:
        TaskLoadError: If file not found, invalid YAML, or validation fails.
    """
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "tasks.yaml"

    # Check if file exists
    if not yaml_path.exists():
        raise TaskLoadError(f"Tasks file not found: {yaml_path}")

    # Parse YAML with error handling
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise TaskLoadError(f"Invalid YAML in {yaml_path}: {e}") from e

    # Check for tasks key
    if not data or "tasks" not in data:
        raise TaskLoadError(f"No 'tasks' key found in {yaml_path}")

    tasks_data = data["tasks"]
    if not isinstance(tasks_data, dict):
        raise TaskLoadError(f"'tasks' must be a dictionary in {yaml_path}")

    # Validate all tasks first, collect errors
    all_errors: list[str] = []
    for task_id, task_data in tasks_data.items():
        if not isinstance(task_data, dict):
            all_errors.append(f"Task {task_id}: must be a dictionary")
            continue
        all_errors.extend(_validate_task(task_id, task_data))

    if all_errors:
        error_msg = "Task validation failed:\n  " + "\n  ".join(all_errors)
        raise TaskLoadError(error_msg)

    # Parse validated tasks
    tasks: dict[str, Task] = {}

    for task_id, task_data in tasks_data.items():
        # Parse ground truth
        ground_truth = [
            GroundTruthItem(
                paper=gt["paper"],
                matchers=gt["matchers"],
            )
            for gt in task_data.get("ground_truth", [])
        ]

        # Parse warm index entries
        warm_entries = [
            WarmIndexEntry(
                description=entry["description"],
                resource=entry["resource"],
            )
            for entry in task_data.get("warm_index_entries", [])
        ]

        tasks[task_id] = Task(
            task_id=task_id,
            family=task_data["family"],
            task_type=task_data["type"],
            prompt=task_data["prompt"],
            ground_truth=ground_truth,
            success_threshold=task_data["success_threshold"],
            warm_index_entries=warm_entries,
            related_task=task_data.get("related_task"),
            primary_task=task_data.get("primary_task"),
        )

    logger.debug(f"Loaded {len(tasks)} tasks from {yaml_path}")
    return tasks


def get_primary_tasks(tasks: dict[str, Task]) -> list[Task]:
    """Get all primary tasks (T1.1, T2.1, T3.1)."""
    return [t for t in tasks.values() if t.task_type == "primary"]


def get_related_task(tasks: dict[str, Task], primary_task_id: str) -> Task | None:
    """Get the related task for a primary task."""
    primary = tasks.get(primary_task_id)
    if primary and primary.related_task:
        return tasks.get(primary.related_task)
    return None


def get_unrelated_task(tasks: dict[str, Task]) -> Task | None:
    """Get the unrelated control task (T0)."""
    for task in tasks.values():
        if task.task_type == "unrelated_control":
            return task
    return None


# Singleton cache
_tasks_cache: dict[str, Task] | None = None


def get_tasks() -> dict[str, Task]:
    """Get cached task definitions."""
    global _tasks_cache
    if _tasks_cache is None:
        _tasks_cache = load_tasks()
    return _tasks_cache
