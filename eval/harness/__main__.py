"""
CLI entry point for the eval harness.

Usage:
    python -m eval.harness [--tasks T1.1 T2.1] [--runs 5] [--model claude-sonnet-4-20250514]

OAuth tokens are saved to .oauth_tokens.json and reused across runs.
Use --reauth to force re-authentication.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Allow running as script or module
if __name__ == "__main__" and __package__ is None:
    # Running as script - add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    __package__ = "eval.harness"

from .config import get_config
from .oauth import get_or_create_oauth
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
  python -m eval.harness --model claude-opus-4-20250514
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
        help="Model ID to use (default: from config)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Force re-authentication (ignore saved tokens)",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Only authenticate and save tokens, don't run eval",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate OAuth by making a test API call",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Get config
    config = get_config()

    # Override model if specified
    if args.model:
        config.model_id = args.model

    print("\n" + "=" * 60)
    print("  Research Accelerator Eval Harness")
    print("=" * 60)
    print(f"\nModel: {config.model_id}")
    print(f"Runs per condition: {args.runs or config.runs_per_condition}")
    if args.tasks:
        print(f"Tasks: {', '.join(args.tasks)}")
    else:
        print("Tasks: All primary tasks")
    print()

    # OAuth authentication (reuses saved tokens if available)
    print("Step 1: Authentication")
    print("-" * 40)
    try:
        oauth = await get_or_create_oauth(force_interactive=args.reauth)
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        print(f"\nError: {e}")
        return 1

    # Exit early if --auth-only
    if args.auth_only and not args.validate:
        print("Authentication complete! Tokens saved for future runs.")
        return 0

    # Validate OAuth with a test API call
    if args.validate:
        print("\nValidating OAuth with test API call...")
        print("-" * 40)
        try:
            from .model import AnthropicOAuthModel

            model = AnthropicOAuthModel(oauth, model_id=config.model_id, max_tokens=100)

            # Make a simple test call with Claude Code system prompt
            test_messages = [{
                "role": "user",
                "content": [{"type": "text", "text": "Say 'hello' and nothing else."}],
            }]
            system_prompt = "You are Claude Code, Anthropic's official CLI for Claude."

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

            print("\n✓ OAuth validation successful! API is working.")

        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            print(f"\n✗ Validation failed: {e}")
            return 1

        if args.auth_only:
            return 0

    # Run evaluation
    print("\nStep 2: Running Evaluation")
    print("-" * 40)
    try:
        runner = EvalRunner(oauth=oauth, config=config)
        results = await runner.run_full_eval(
            task_ids=args.tasks,
            runs_per_condition=args.runs,
        )
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        print(f"\nError during evaluation: {e}")
        return 1

    # Save results
    print("\nStep 3: Saving Results")
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
        success_rate = sum(1 for r in runs if r.success) / len(runs) * 100
        avg_tokens = sum(r.total_tokens for r in runs) / len(runs)
        print(f"\n{condition}:")
        print(f"  Runs: {len(runs)}")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Avg tokens: {avg_tokens:.0f}")

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
