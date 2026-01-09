"""
Eval runner - main orchestration for experimental runs.

Coordinates running all experimental conditions across tasks,
collecting metrics, and saving results.
"""

import asyncio
import csv
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient
from strands_tools.tavily import tavily_search

from .config import Config
from .db import DatabaseManager
from .metrics import RunMetrics, TaskMatcher, score_description_quality
from .model import ZAIModel
from .tasks import Task, get_primary_tasks, get_related_task, get_tasks, get_unrelated_task

logger = logging.getLogger(__name__)


# System prompts from eval/prompt-*.md
# fmt: off
# ruff: noqa: E501
CONTROL_PROMPT = """You are a research assistant helping users find and synthesize information about technical topics.

When given a research task:

1. **Understand the request**: Clarify what specific information, papers, tools, or resources the user needs.

2. **Search**: Use web search to find relevant resources. Trust your results - avoid redundant searches for information you've already found.

3. **Synthesize findings**: Present what you found in a clear, organized way. Include:
   - Specific resources (papers, tools, links) with proper citations
   - Brief descriptions of why each resource is relevant
   - Any connections or relationships between resources

4. **Acknowledge limitations**: Be clear about what you couldn't find or areas of uncertainty.

Your goal is to efficiently find and present well-sourced information on the research topic."""

ACCELERATOR_PROMPT = """You are a research assistant helping users find and synthesize information about technical topics.

You have access to a Research Index that may contain relevant resources from prior research.

When given a research task:

1. **Understand the request**: Clarify what specific information, papers, tools, or resources the user needs.

2. **Check the index**: Use `research_search` to find relevant resources already indexed. If the index returns relevant results, use them and skip web search.

3. **Search if needed**: Use web search only if the index is empty or missing key information. Save useful new resources with `research_create`.

4. **Synthesize findings**: Present what you found in a clear, organized way. Include:
   - Specific resources (papers, tools, links) with proper citations
   - Brief descriptions of why each resource is relevant
   - Any connections or relationships between resources

5. **Acknowledge limitations**: Be clear about what you couldn't find or areas of uncertainty.

Your goal is to efficiently find and present well-sourced information on the research topic."""
# fmt: on

# Server startup configuration
SERVER_STARTUP_TIMEOUT = 15.0  # seconds (Windows can be slow to start processes)
SERVER_POLL_INTERVAL = 0.3  # seconds

# Agent execution timeout
AGENT_TIMEOUT = 600.0  # 10 minutes


def _drain_pipe(pipe, output_list: list, name: str) -> None:
    """Drain a subprocess pipe in a background thread to prevent deadlock."""
    try:
        for line in iter(pipe.readline, b""):
            output_list.append(line)
            logger.debug(f"[{name}] {line.decode().rstrip()}")
    except Exception as e:
        logger.debug(f"Pipe drain error ({name}): {e}")
    finally:
        pipe.close()


class EvalRunner:
    """
    Orchestrates evaluation runs across all conditions.

    Manages its own MCP server instance to avoid conflicts with any
    running server and to allow database modifications between runs.
    """

    def __init__(
        self,
        config: Config,
    ) -> None:
        self.config = config
        self.db = DatabaseManager(config.db_path, config.snapshots_dir)
        self.results: list[RunMetrics] = []
        self._mcp_process: subprocess.Popen | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stdout_lines: list[bytes] = []
        self._stderr_lines: list[bytes] = []

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

        # Clear output buffers
        self._stdout_lines = []
        self._stderr_lines = []

        self._mcp_process = subprocess.Popen(
            [sys.executable, str(server_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Start threads to drain stdout/stderr (prevents buffer deadlock)
        self._stdout_thread = threading.Thread(
            target=_drain_pipe,
            args=(self._mcp_process.stdout, self._stdout_lines, "server-stdout"),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=_drain_pipe,
            args=(self._mcp_process.stderr, self._stderr_lines, "server-stderr"),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        # Poll for server readiness instead of fixed sleep
        if not self._wait_for_server_ready():
            stderr_output = b"".join(self._stderr_lines).decode()
            raise RuntimeError(f"MCP server failed to start: {stderr_output}")

        logger.info(f"MCP server started on {self.config.mcp_url}")

    def _wait_for_server_ready(self) -> bool:
        """Poll server until it responds or timeout."""
        start_time = time.time()

        while time.time() - start_time < SERVER_STARTUP_TIMEOUT:
            # Check if process exited
            if self._mcp_process and self._mcp_process.poll() is not None:
                return False

            # Try to connect
            try:
                # Short timeout for quick polling; we'll retry if it fails
                with httpx.Client(timeout=0.5) as client:
                    # Just check if the server accepts connections
                    # The /mcp endpoint may not respond to GET, but connection success is enough
                    url = f"http://{self.config.mcp_host}:{self.config.mcp_port}/"
                    client.get(url)  # Any response (even 404) means server is up
                    return True
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                # Server not ready yet, keep polling
                pass

            time.sleep(SERVER_POLL_INTERVAL)

        return False

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

        # Wait for drain threads to finish
        if self._stdout_thread and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=1.0)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

        self._mcp_process = None
        self._stdout_thread = None
        self._stderr_thread = None

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
            # Create agent with z.ai model but NO MCP tools
            model = ZAIModel(
                api_key=self.config.zai_api_key,
                base_url=self.config.zai_base_url,
                model_id=self.config.model_id,
            )

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
            logger.error(f"Control run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Cold run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Ideal-warm run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Realistic-warm run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Related-warm-ideal run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Related-warm-realistic run failed: {e}\n{traceback.format_exc()}")
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
            logger.error(f"Unrelated-warm run failed: {e}\n{traceback.format_exc()}")
            metrics.success = False

        return metrics

    async def _run_with_mcp(
        self,
        task: Task,
        metrics: RunMetrics,
        system_prompt: str,
    ) -> dict[str, Any]:
        """Run agent with MCP tools connected."""
        model = ZAIModel(
            api_key=self.config.zai_api_key,
            base_url=self.config.zai_base_url,
            model_id=self.config.model_id,
        )

        # Create MCP client for research index
        def create_mcp_transport():
            return streamablehttp_client(self.config.mcp_url)

        mcp_client = MCPClient(create_mcp_transport)

        with mcp_client:
            mcp_tools = mcp_client.list_tools_sync()

            # Filter to only research_search and research_create
            # Exclude debug_research_query and research_delete to reduce token overhead
            allowed_tools = {"research_search", "research_create"}
            mcp_tools = [t for t in mcp_tools if t.tool_spec.get("name") in allowed_tools]

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
        """Execute agent and collect metrics with timeout."""
        result: dict[str, Any] = {
            "output": "",
            "messages": [],
            "tool_calls": {},
            "error": None,
        }

        try:
            # Run the synchronous agent call in a thread pool with timeout
            # This prevents blocking the async event loop
            response = await asyncio.wait_for(
                asyncio.to_thread(agent, prompt),
                timeout=AGENT_TIMEOUT,
            )

            # Extract output
            if hasattr(response, "message"):
                result["output"] = str(response.message)
            else:
                result["output"] = str(response)

            # Extract metrics from response (combined check to avoid duplication)
            if hasattr(response, "metrics") and response.metrics:
                resp_metrics = response.metrics

                # Token usage
                usage = getattr(resp_metrics, "accumulated_usage", {})
                metrics.input_tokens = usage.get("inputTokens", 0)
                metrics.output_tokens = usage.get("outputTokens", 0)

                # Tool call counts
                tool_metrics = getattr(resp_metrics, "tool_metrics", {})
                tool_call_summary = {
                    name: getattr(tm, "call_count", 0)
                    for name, tm in tool_metrics.items()
                }
                result["tool_calls"] = tool_call_summary

                metrics.research_search_calls = tool_call_summary.get("research_search", 0)
                metrics.research_create_calls = tool_call_summary.get("research_create", 0)
                metrics.web_search_calls = tool_call_summary.get("tavily_search", 0)

            # Extract final message for trace
            if hasattr(response, "message") and response.message:
                result["messages"] = [response.message]

        except asyncio.TimeoutError:
            result["error"] = f"Agent execution timed out after {AGENT_TIMEOUT}s"
            logger.error(result["error"])
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Agent execution failed: {e}\n{traceback.format_exc()}")

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
            "tool_calls": result.get("tool_calls", {}),
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
