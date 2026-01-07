"""
Eval runner - main orchestration for experimental runs.

Coordinates running all experimental conditions across tasks,
collecting metrics, and saving results.
"""

import csv
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient

from .config import Config
from .db import DatabaseManager
from .metrics import (
    RunMetrics,
    TaskMatcher,
    count_tool_calls,
    score_description_quality,
)
from .model import AnthropicOAuthModel
from .oauth import OAuthManager
from .tasks import Task, get_primary_tasks, get_related_task, get_tasks, get_unrelated_task

logger = logging.getLogger(__name__)


# Claude Code system prompt prefix (required for OAuth authentication!)
CLAUDE_CODE_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude.\n\n"

# System prompts from eval/prompt-*.md
CONTROL_PROMPT = CLAUDE_CODE_PREFIX + """You are a research assistant helping users find and synthesize information about technical topics.

When given a research task:

1. **Understand the request**: Clarify what specific information, papers, tools, or resources the user needs.

2. **Search systematically**: Use web search to find relevant resources. Try multiple query formulations if initial searches don't yield good results.

3. **Evaluate sources**: Prioritize primary sources (original papers, official documentation) over secondary summaries.

4. **Synthesize findings**: Present what you found in a clear, organized way. Include:
   - Specific resources (papers, tools, links) with proper citations
   - Brief descriptions of why each resource is relevant
   - Any connections or relationships between resources

5. **Acknowledge limitations**: Be clear about what you couldn't find or areas of uncertainty.

Your goal is to help the user build a comprehensive understanding of their research topic with actionable, well-sourced information."""

ACCELERATOR_PROMPT = CLAUDE_CODE_PREFIX + """You are a research assistant helping users find and synthesize information about technical topics.

You have access to a Research Index that stores and retrieves research resources. This index persists across conversations.

When given a research task:

1. **Understand the request**: Clarify what specific information, papers, tools, or resources the user needs.

2. **Check the index**: Use `research_search` to see if relevant resources have already been indexed from prior research.

3. **Search systematically**: Use web search to find relevant resources not in the index. Try multiple query formulations if initial searches don't yield good results.

4. **Evaluate sources**: Prioritize primary sources (original papers, official documentation) over secondary summaries.

5. **Index new discoveries**: Use `research_create` to save useful NEW resources you found (skip if already in index), with descriptions that will help future searches.

6. **Synthesize findings**: Present what you found in a clear, organized way. Include:
   - Specific resources (papers, tools, links) with proper citations
   - Brief descriptions of why each resource is relevant
   - Any connections or relationships between resources

7. **Acknowledge limitations**: Be clear about what you couldn't find or areas of uncertainty.

Your goal is to help the user build a comprehensive understanding of their research topic with actionable, well-sourced information."""


class EvalRunner:
    """
    Orchestrates evaluation runs across all conditions.

    Manages its own MCP server instance to avoid conflicts with any
    running server and to allow database modifications between runs.
    """

    def __init__(
        self,
        oauth: OAuthManager,
        config: Config,
    ) -> None:
        self.oauth = oauth
        self.config = config
        self.db = DatabaseManager(config.db_path, config.snapshots_dir)
        self.results: list[RunMetrics] = []
        self._mcp_process: subprocess.Popen | None = None

        # Ensure output directories exist
        config.results_dir.mkdir(parents=True, exist_ok=True)
        config.traces_dir.mkdir(parents=True, exist_ok=True)

    def _start_mcp_server(self) -> None:
        """Start the eval's MCP server subprocess."""
        if self._mcp_process is not None:
            return  # Already running

        # Find the server.py path (relative to this package)
        server_path = Path(__file__).parent.parent.parent / "server.py"

        # Start server with eval-specific database
        env = os.environ.copy()
        env["RESEARCH_DB_PATH"] = str(self.config.db_path)
        env["PORT"] = str(self.config.mcp_port)
        env["HOST"] = self.config.mcp_host

        logger.debug(f"Starting MCP server on port {self.config.mcp_port}")
        self._mcp_process = subprocess.Popen(
            [sys.executable, str(server_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        time.sleep(1.0)

        if self._mcp_process.poll() is not None:
            # Server exited immediately - something went wrong
            stderr = self._mcp_process.stderr.read().decode() if self._mcp_process.stderr else ""
            raise RuntimeError(f"MCP server failed to start: {stderr}")

        logger.info(f"MCP server started on {self.config.mcp_url}")

    def _stop_mcp_server(self) -> None:
        """Stop the eval's MCP server subprocess."""
        if self._mcp_process is None:
            return

        logger.debug("Stopping MCP server")
        self._mcp_process.terminate()
        try:
            self._mcp_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._mcp_process.kill()
            self._mcp_process.wait()

        self._mcp_process = None
        # Small delay to ensure file handles are released (Windows)
        time.sleep(0.5)
        logger.info("MCP server stopped")

    def _restart_mcp_server(self) -> None:
        """Restart the MCP server (for database changes)."""
        self._stop_mcp_server()
        self._start_mcp_server()

    async def run_full_eval(
        self,
        task_ids: list[str] | None = None,
        runs_per_condition: int | None = None,
    ) -> list[RunMetrics]:
        """
        Run the full evaluation across all tasks and conditions.

        Args:
            task_ids: Specific tasks to run (defaults to all primary tasks)
            runs_per_condition: Override config runs per condition

        Returns:
            List of all run metrics
        """
        all_tasks = get_tasks()
        runs = runs_per_condition or self.config.runs_per_condition

        # Determine which primary tasks to run
        if task_ids:
            primary_tasks = [all_tasks[tid] for tid in task_ids if tid in all_tasks]
        else:
            primary_tasks = get_primary_tasks(all_tasks)

        logger.info(
            f"Running eval with {len(primary_tasks)} primary tasks, {runs} runs per condition"
        )

        try:
            for task in primary_tasks:
                await self._run_task_family(task, all_tasks, runs)
        finally:
            # Always stop server on exit
            self._stop_mcp_server()

        return self.results

    async def _run_task_family(
        self,
        primary_task: Task,
        all_tasks: dict[str, Task],
        runs: int,
    ) -> None:
        """Run all conditions for a task family."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Task Family: {primary_task.family} ({primary_task.task_id})")
        logger.info(f"{'='*60}")

        # Get related and unrelated tasks
        related_task = get_related_task(all_tasks, primary_task.task_id)
        unrelated_task = get_unrelated_task(all_tasks)

        # 1. CONTROL runs
        logger.info(f"\n--- CONTROL ({runs} runs) ---")
        for i in range(1, runs + 1):
            metrics = await self._run_control(primary_task, i)
            self.results.append(metrics)

        # 2. COLD runs (snapshot after first)
        logger.info(f"\n--- COLD ({runs} runs) ---")
        cold_snapshot: Path | None = None
        for i in range(1, runs + 1):
            metrics, snapshot = await self._run_cold(primary_task, i)
            self.results.append(metrics)
            if i == 1:
                cold_snapshot = snapshot

        # 3. IDEAL-WARM runs
        logger.info(f"\n--- IDEAL-WARM ({runs} runs) ---")
        for i in range(1, runs + 1):
            metrics = await self._run_ideal_warm(primary_task, i)
            self.results.append(metrics)

        # 4. REALISTIC-WARM runs (using cold snapshot)
        if cold_snapshot:
            logger.info(f"\n--- REALISTIC-WARM ({runs} runs) ---")
            for i in range(1, runs + 1):
                metrics = await self._run_realistic_warm(primary_task, i, cold_snapshot)
                self.results.append(metrics)

        # 5. RELATED-WARM runs (ideal and realistic)
        if related_task and primary_task.warm_index_entries:
            # Ideal
            logger.info(f"\n--- RELATED-WARM-IDEAL ({runs} runs on {related_task.task_id}) ---")
            for i in range(1, runs + 1):
                metrics = await self._run_related_warm_ideal(related_task, primary_task, i)
                self.results.append(metrics)

            # Realistic
            if cold_snapshot:
                logger.info(
                    f"\n--- RELATED-WARM-REALISTIC ({runs} runs on {related_task.task_id}) ---"
                )
                for i in range(1, runs + 1):
                    metrics = await self._run_related_warm_realistic(
                        related_task, i, cold_snapshot
                    )
                    self.results.append(metrics)

        # 6. UNRELATED-WARM runs
        if unrelated_task and cold_snapshot:
            logger.info(f"\n--- UNRELATED-WARM ({runs} runs on {unrelated_task.task_id}) ---")
            for i in range(1, runs + 1):
                metrics = await self._run_unrelated_warm(
                    unrelated_task, i, cold_snapshot
                )
                self.results.append(metrics)

    async def _run_control(self, task: Task, run: int) -> RunMetrics:
        """Run a control condition (no MCP, web search only)."""
        logger.info(f"  Control run {run}/{task.task_id}")

        metrics = RunMetrics(
            task_id=task.task_id,
            condition="control",
            run_number=run,
        )

        try:
            # Create agent with OAuth model but NO MCP tools
            model = AnthropicOAuthModel(
                self.oauth,
                model_id=self.config.model_id,
            )

            # Get web search tools (tavily)
            # For control, we just use web search
            from strands_tools.tavily import tavily_search

            agent = Agent(
                model=model,
                tools=[tavily_search],
                system_prompt=CONTROL_PROMPT,
            )

            # Run the agent
            result = await self._execute_agent(agent, task.prompt, metrics)

            # Evaluate success
            matcher = TaskMatcher(
                task.get_matchers_for_metrics(),
                task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Control run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_cold(self, task: Task, run: int) -> tuple[RunMetrics, Path | None]:
        """Run a cold condition (empty DB)."""
        logger.info(f"  Cold run {run}/{task.task_id}")

        metrics = RunMetrics(
            task_id=task.task_id,
            condition="cold",
            run_number=run,
        )

        snapshot_path: Path | None = None

        try:
            # Stop server, clear database, restart server
            self._stop_mcp_server()
            self.db.clear_database()
            self._start_mcp_server()

            # Run with MCP
            result = await self._run_with_mcp(task, metrics, ACCELERATOR_PROMPT)

            # Score description quality for entries created
            entries = self.db.get_all_entries()
            for entry in entries:
                score = score_description_quality(entry["description"])
                metrics.description_quality_scores.append(score)

            # Evaluate success
            matcher = TaskMatcher(
                task.get_matchers_for_metrics(),
                task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Create snapshot
            snapshot_path = self.db.create_snapshot(task.task_id, run)

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Cold run failed: {e}")
            metrics.success = False

        return metrics, snapshot_path

    async def _run_ideal_warm(self, task: Task, run: int) -> RunMetrics:
        """Run ideal-warm condition (hand-crafted entries)."""
        logger.info(f"  Ideal-warm run {run}/{task.task_id}")

        metrics = RunMetrics(
            task_id=task.task_id,
            condition="ideal_warm",
            run_number=run,
        )

        try:
            # Stop server, load hand-crafted entries, restart server
            self._stop_mcp_server()
            entries = [
                {"description": e.description, "resource": e.resource}
                for e in task.warm_index_entries
            ]
            self.db.load_ideal_warm_entries(entries)
            self._start_mcp_server()

            # Run with MCP
            result = await self._run_with_mcp(task, metrics, ACCELERATOR_PROMPT)

            # Evaluate success
            matcher = TaskMatcher(
                task.get_matchers_for_metrics(),
                task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Ideal-warm run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_realistic_warm(
        self,
        task: Task,
        run: int,
        snapshot: Path,
    ) -> RunMetrics:
        """Run realistic-warm condition (restore cold snapshot)."""
        logger.info(f"  Realistic-warm run {run}/{task.task_id}")

        metrics = RunMetrics(
            task_id=task.task_id,
            condition="realistic_warm",
            run_number=run,
        )

        try:
            # Stop server, restore from cold snapshot, restart server
            self._stop_mcp_server()
            self.db.restore_snapshot(snapshot)
            self._start_mcp_server()

            # Run with MCP
            result = await self._run_with_mcp(task, metrics, ACCELERATOR_PROMPT)

            # Evaluate success
            matcher = TaskMatcher(
                task.get_matchers_for_metrics(),
                task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Realistic-warm run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_related_warm_ideal(
        self,
        related_task: Task,
        primary_task: Task,
        run: int,
    ) -> RunMetrics:
        """Run related-warm-ideal condition."""
        logger.info(f"  Related-warm-ideal run {run}/{related_task.task_id}")

        metrics = RunMetrics(
            task_id=related_task.task_id,
            condition="related_warm_ideal",
            run_number=run,
        )

        try:
            # Stop server, load primary task's entries, restart server
            self._stop_mcp_server()
            entries = [
                {"description": e.description, "resource": e.resource}
                for e in primary_task.warm_index_entries
            ]
            self.db.load_ideal_warm_entries(entries)
            self._start_mcp_server()

            # Run RELATED task with MCP
            result = await self._run_with_mcp(related_task, metrics, ACCELERATOR_PROMPT)

            # Evaluate success against RELATED task's ground truth
            matcher = TaskMatcher(
                related_task.get_matchers_for_metrics(),
                related_task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Related-warm-ideal run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_related_warm_realistic(
        self,
        related_task: Task,
        run: int,
        snapshot: Path,
    ) -> RunMetrics:
        """Run related-warm-realistic condition."""
        logger.info(f"  Related-warm-realistic run {run}/{related_task.task_id}")

        metrics = RunMetrics(
            task_id=related_task.task_id,
            condition="related_warm_realistic",
            run_number=run,
        )

        try:
            # Stop server, restore from primary task's snapshot, restart server
            self._stop_mcp_server()
            self.db.restore_snapshot(snapshot)
            self._start_mcp_server()

            # Run RELATED task with MCP
            result = await self._run_with_mcp(related_task, metrics, ACCELERATOR_PROMPT)

            # Evaluate success
            matcher = TaskMatcher(
                related_task.get_matchers_for_metrics(),
                related_task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Related-warm-realistic run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_unrelated_warm(
        self,
        unrelated_task: Task,
        run: int,
        snapshot: Path,
    ) -> RunMetrics:
        """Run unrelated-warm condition."""
        logger.info(f"  Unrelated-warm run {run}/{unrelated_task.task_id}")

        metrics = RunMetrics(
            task_id=unrelated_task.task_id,
            condition="unrelated_warm",
            run_number=run,
        )

        try:
            # Stop server, restore from primary task's snapshot, restart server
            self._stop_mcp_server()
            self.db.restore_snapshot(snapshot)
            self._start_mcp_server()

            # Run UNRELATED task (T0) with MCP
            result = await self._run_with_mcp(unrelated_task, metrics, ACCELERATOR_PROMPT)

            # Evaluate success against T0's ground truth
            matcher = TaskMatcher(
                unrelated_task.get_matchers_for_metrics(),
                unrelated_task.success_threshold,
            )
            found, success = matcher.evaluate_output(result.get("output", ""))
            metrics.resources_found = found
            metrics.success = success

            # Save trace
            self._save_trace(metrics, result)

        except Exception as e:
            logger.error(f"Unrelated-warm run failed: {e}")
            metrics.success = False

        return metrics

    async def _run_with_mcp(
        self,
        task: Task,
        metrics: RunMetrics,
        system_prompt: str,
    ) -> dict[str, Any]:
        """Run agent with MCP tools connected."""
        model = AnthropicOAuthModel(
            self.oauth,
            model_id=self.config.model_id,
        )

        # Create MCP client for research index
        def create_mcp_transport():
            return streamablehttp_client(self.config.mcp_url)

        mcp_client = MCPClient(create_mcp_transport)

        # Get web search tools
        from strands_tools.tavily import tavily_search

        with mcp_client:
            mcp_tools = mcp_client.list_tools_sync()

            agent = Agent(
                model=model,
                tools=[tavily_search, *mcp_tools],
                system_prompt=system_prompt,
            )

            return await self._execute_agent(agent, task.prompt, metrics)

    async def _execute_agent(
        self,
        agent: Agent,
        prompt: str,
        metrics: RunMetrics,
    ) -> dict[str, Any]:
        """Execute agent and collect metrics."""
        result: dict[str, Any] = {
            "output": "",
            "messages": [],
            "tool_calls": [],
            "error": None,
        }

        try:
            # Run the agent
            response = agent(prompt)

            # Extract output
            if hasattr(response, "message"):
                result["output"] = str(response.message)
            else:
                result["output"] = str(response)

            # Extract metrics from response
            if hasattr(response, "metrics"):
                resp_metrics = response.metrics
                metrics.input_tokens = getattr(resp_metrics, "input_tokens", 0)
                metrics.output_tokens = getattr(resp_metrics, "output_tokens", 0)

            # Extract tool calls
            if hasattr(response, "tool_calls"):
                result["tool_calls"] = response.tool_calls
                search, create, web = count_tool_calls([], response.tool_calls)
                metrics.research_search_calls = search
                metrics.research_create_calls = create
                metrics.web_search_calls = web

            # Extract messages for trace
            if hasattr(response, "messages"):
                result["messages"] = response.messages

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Agent execution failed: {e}")

        return result

    def _save_trace(self, metrics: RunMetrics, result: dict[str, Any]) -> None:
        """Save conversation trace for debugging."""
        trace_path = self.config.traces_dir / f"{metrics.run_id}.json"

        trace_data = {
            "run_id": metrics.run_id,
            "task_id": metrics.task_id,
            "condition": metrics.condition,
            "run_number": metrics.run_number,
            "timestamp": metrics.timestamp.isoformat(),
            "metrics": {
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
                "success": metrics.success,
                "resources_found": metrics.resources_found,
            },
            "messages": result.get("messages", []),
            "tool_calls": result.get("tool_calls", []),
            "output": result.get("output", ""),
            "error": result.get("error"),
        }

        with open(trace_path, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)


def save_results_csv(results: list[RunMetrics], output_dir: Path) -> Path:
    """Save results to CSV file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"results_{timestamp}.csv"

    fieldnames = [
        "run_id",
        "task_id",
        "condition",
        "run_number",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "research_search_calls",
        "research_create_calls",
        "web_search_calls",
        "resources_found",
        "success",
        "description_quality_avg",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for metrics in results:
            writer.writerow(metrics.to_csv_row())

    return csv_path
