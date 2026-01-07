"""
Task definitions loader.

Loads structured task definitions from eval/tasks.yaml.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

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


def load_tasks(yaml_path: Path | None = None) -> dict[str, Task]:
    """
    Load task definitions from YAML file.

    Args:
        yaml_path: Path to tasks.yaml. Defaults to eval/tasks.yaml.

    Returns:
        Dictionary mapping task_id to Task objects.
    """
    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent / "tasks.yaml"

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    tasks: dict[str, Task] = {}

    for task_id, task_data in data.get("tasks", {}).items():
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
            family=task_data.get("family", ""),
            task_type=task_data.get("type", "primary"),
            prompt=task_data.get("prompt", ""),
            ground_truth=ground_truth,
            success_threshold=task_data.get("success_threshold", 2),
            warm_index_entries=warm_entries,
            related_task=task_data.get("related_task"),
            primary_task=task_data.get("primary_task"),
        )

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
