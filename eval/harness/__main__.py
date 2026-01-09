"""
CLI entry point for the eval harness.

Usage:
    python -m eval.harness [--tasks T1.1 T2.1] [--runs 5] [--model GLM-4.7]

Requires ZAI_API_KEY environment variable to be set.
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path

# Allow running as script or module
if __name__ == "__main__" and __package__ is None:
    # Running as script - add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    __package__ = "eval.harness"

from .config import ConfigError, get_config
from .runner import EvalRunner, save_results_csv


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Research Accelerator Eval Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full eval with default settings
  python -m eval.harness

  # Run specific tasks with 3 runs each
  python -m eval.harness --tasks T1.1 T2.1 --runs 3

  # Run with a different model
  python -m eval.harness --model GLM-4.5-Air

  # Validate API connection before running
  python -m eval.harness --validate
        """,
    )

    parser.add_argument(
        "--tasks",
        nargs="+",
        help="Specific task IDs to run (default: all primary tasks)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        help="Number of runs per condition (default: from config)",
    )
    parser.add_argument(
        "--model",
        help="Model ID to use (default: GLM-4.7)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate API connection by making a test call",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Get config (create modified copy if overrides specified, don't mutate singleton)
    try:
        config = get_config()
    except ConfigError as e:
        print(f"\nConfiguration error: {e}")
        return 1

    if args.model:
        config = replace(config, model_id=args.model)

    print("\n" + "=" * 60)
    print("  Research Accelerator Eval Harness")
    print("=" * 60)
    print(f"\nModel: {config.model_id}")
    print(f"API: {config.zai_base_url}")
    print(f"Runs per condition: {args.runs or config.runs_per_condition}")
    if args.tasks:
        print(f"Tasks: {', '.join(args.tasks)}")
    else:
        print("Tasks: All primary tasks")
    print()

    # Validate API connection if requested
    if args.validate:
        print("Step 1: Validating API Connection")
        print("-" * 40)
        try:
            from .model import ZAIModel

            model = ZAIModel(
                api_key=config.zai_api_key,
                base_url=config.zai_base_url,
                model_id=config.model_id,
                max_tokens=100,
            )

            # Make a simple test call
            test_messages = [{
                "role": "user",
                "content": [{"type": "text", "text": "Say 'hello' and nothing else."}],
            }]
            system_prompt = "You are a helpful assistant."

            response_text = ""
            async for event in model.stream(test_messages, system_prompt=system_prompt):
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        response_text += delta["text"]
                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {})
                    print(f"\nAPI Response: {response_text.strip()}")
                    print(f"Tokens used: {usage.get('totalTokens', 'unknown')}")

            print("\n✓ API validation successful!")
            print()

        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            print(f"\n✗ Validation failed: {e}")
            return 1

    # Run evaluation
    step_num = 2 if args.validate else 1
    print(f"Step {step_num}: Running Evaluation")
    print("-" * 40)
    try:
        runner = EvalRunner(config=config)
        results = await runner.run_full_eval(
            task_ids=args.tasks,
            runs_per_condition=args.runs,
        )
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        print(f"\nError during evaluation: {e}")
        return 1

    # Save results
    step_num += 1
    print(f"\nStep {step_num}: Saving Results")
    print("-" * 40)
    try:
        csv_path = save_results_csv(results, config.results_dir)
        print(f"Results saved to: {csv_path}")
    except Exception as e:
        logger.error(f"Failed to save results: {e}")
        print(f"\nError saving results: {e}")
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)

    # Group by condition
    by_condition: dict[str, list] = {}
    for r in results:
        by_condition.setdefault(r.condition, []).append(r)

    for condition, runs in sorted(by_condition.items()):
        num_runs = len(runs)
        print(f"\n{condition}:")
        print(f"  Runs: {num_runs}")
        if num_runs > 0:
            success_rate = sum(1 for r in runs if r.success) / num_runs * 100
            avg_tokens = sum(r.total_tokens for r in runs) / num_runs
            print(f"  Success rate: {success_rate:.1f}%")
            print(f"  Avg tokens: {avg_tokens:.0f}")
        else:
            print("  (no runs completed)")

    print(f"\nTotal runs: {len(results)}")
    print(f"Results: {csv_path}")
    print(f"Traces: {config.traces_dir}")
    print()

    return 0


def cli() -> None:
    """CLI wrapper for sync context."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
