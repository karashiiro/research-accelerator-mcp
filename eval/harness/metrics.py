"""
Metrics collection and task success evaluation.

Provides:
- RunMetrics dataclass for storing eval run results
- TaskMatcher for evaluating if agent found ground truth resources
- Description quality scoring for cold runs
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ConditionType = Literal[
    "control",
    "cold",
    "ideal_warm",
    "realistic_warm",
    "related_warm_ideal",
    "related_warm_realistic",
    "unrelated_warm",
]


@dataclass
class RunMetrics:
    """Metrics for a single eval run."""

    # Identifiers
    task_id: str
    condition: ConditionType
    run_number: int

    # Tokens
    input_tokens: int = 0
    output_tokens: int = 0

    # Tool calls
    research_search_calls: int = 0
    research_create_calls: int = 0
    web_search_calls: int = 0

    # Results
    resources_found: list[str] = field(default_factory=list)
    success: bool = False

    # Description quality (cold runs only)
    description_quality_scores: list[int] = field(default_factory=list)

    # Timing
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens

    @property
    def run_id(self) -> str:
        """Generate unique run ID."""
        ts = self.timestamp.strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{self.task_id}_{self.condition}_{self.run_number}"

    @property
    def description_quality_avg(self) -> float | None:
        """Average description quality score, or None if no descriptions."""
        if not self.description_quality_scores:
            return None
        return sum(self.description_quality_scores) / len(self.description_quality_scores)

    def to_csv_row(self) -> dict[str, str]:
        """Convert to CSV row dict."""
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "condition": self.condition,
            "run_number": str(self.run_number),
            "input_tokens": str(self.input_tokens),
            "output_tokens": str(self.output_tokens),
            "total_tokens": str(self.total_tokens),
            "research_search_calls": str(self.research_search_calls),
            "research_create_calls": str(self.research_create_calls),
            "web_search_calls": str(self.web_search_calls),
            "resources_found": ",".join(self.resources_found),
            "success": str(self.success).lower(),
            "description_quality_avg": (
                f"{self.description_quality_avg:.1f}"
                if self.description_quality_avg is not None
                else ""
            ),
        }


class TaskMatcher:
    """
    Evaluates if agent output contains ground truth resources.

    Uses regex matching against a list of patterns for each resource.
    """

    def __init__(
        self,
        ground_truth: list[dict[str, list[str]]],
        success_threshold: int,
    ) -> None:
        """
        Initialize matcher with ground truth.

        Args:
            ground_truth: List of dicts with 'paper' and 'matchers' keys.
                          'matchers' is a list of regex patterns.
            success_threshold: Minimum number of resources to find for success.
        """
        self.ground_truth = ground_truth
        self.success_threshold = success_threshold

        # Pre-compile regex patterns
        self._compiled_patterns: list[tuple[str, list[re.Pattern]]] = []
        for item in ground_truth:
            paper = item.get("paper", "")
            patterns = [
                re.compile(p, re.IGNORECASE)
                for p in item.get("matchers", [])
            ]
            self._compiled_patterns.append((paper, patterns))

    def evaluate_output(self, agent_output: str) -> tuple[list[str], bool]:
        """
        Evaluate agent output against ground truth.

        Args:
            agent_output: The full text output from the agent.

        Returns:
            Tuple of (list of found resource names, success boolean)
        """
        found_resources = []

        for paper, patterns in self._compiled_patterns:
            for pattern in patterns:
                if pattern.search(agent_output):
                    found_resources.append(paper)
                    break  # Only need one match per paper

        success = len(found_resources) >= self.success_threshold
        return found_resources, success


def score_description_quality(description: str) -> int:
    """
    Score the quality of an agent-generated description.

    Criteria (0-5 points):
    - Contains author name(s): +1
    - Contains year: +1
    - Contains paper title or fragment: +1
    - Contains key technical terms: +1
    - Length >= 50 characters: +1

    Args:
        description: The description text to score.

    Returns:
        Quality score from 0 to 5.
    """
    score = 0

    # Check for author name patterns (e.g., "Vaswani", "et al")
    author_pattern = r"\b[A-Z][a-z]+\s+(et al\.?|and|&)"
    if re.search(author_pattern, description):
        score += 1

    # Check for year (4 digit number starting with 19 or 20)
    year_pattern = r"\b(19|20)\d{2}\b"
    if re.search(year_pattern, description):
        score += 1

    # Check for paper title indicators
    # Look for quoted text, title case sequences, or common title words
    title_patterns = [
        r'"[^"]+"',  # Quoted text
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}",  # Title case sequence
        r"\b(Attention|Transformer|Neural|Learning|Model|Generation)\b",  # Common ML title words
    ]
    for pattern in title_patterns:
        if re.search(pattern, description):
            score += 1
            break

    # Check for technical terms
    tech_terms = [
        r"\battention\b",
        r"\btransformer\b",
        r"\bself-attention\b",
        r"\bembedding\b",
        r"\bencoder\b",
        r"\bdecoder\b",
        r"\bsequence\b",
        r"\bneural\b",
        r"\bretrieval\b",
        r"\bgeneration\b",
        r"\bRAG\b",
        r"\bFTS\b",
        r"\bpositional\b",
        r"\bbenchmark\b",
        r"\bcode\b",
        r"\bsynthesis\b",
    ]
    for term in tech_terms:
        if re.search(term, description, re.IGNORECASE):
            score += 1
            break

    # Check length
    if len(description) >= 50:
        score += 1

    return min(score, 5)  # Cap at 5


def count_tool_calls(
    messages: list[dict],
    tool_calls: list[dict],
) -> tuple[int, int, int]:
    """
    Count different types of tool calls from agent execution.

    Args:
        messages: List of conversation messages.
        tool_calls: List of tool call records.

    Returns:
        Tuple of (research_search_calls, research_create_calls, web_search_calls)
    """
    research_search = 0
    research_create = 0
    web_search = 0

    for call in tool_calls:
        name = call.get("name", "").lower()

        if "research_search" in name:
            research_search += 1
        elif "research_create" in name:
            research_create += 1
        elif "tavily" in name or "web_search" in name or "search" in name:
            web_search += 1

    return research_search, research_create, web_search
