"""CLI entry point for hallucifix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .orchestrator import HallucifixConfig, Orchestrator, ProcessConfig


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="hallucifix",
        description="Attach debuggers, run tests, and AI-fix failures in a loop.",
    )
    parser.add_argument(
        "test_path",
        help="Path to the test file or directory to run",
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to hallucifix config JSON file",
    )
    parser.add_argument(
        "-p", "--process",
        action="append",
        metavar="NAME:PORT:LOGFILE",
        help="Process to monitor (format: name:debugpy_port:log_file). "
             "Port and log_file are optional. Can be specified multiple times.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum fix iterations (default: 5)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="LLM model to use (default: gpt-4o)",
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (or set OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        help="OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--project-root",
        help="Project root directory (default: cwd)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Test timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--pytest-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Additional arguments to pass to pytest",
    )

    args = parser.parse_args()

    # Build config
    if args.config:
        config = _load_config_file(args.config)
    else:
        config = HallucifixConfig(test_path=args.test_path)

    # Override with CLI args
    config.test_path = args.test_path
    config.max_fix_iterations = args.max_iterations
    config.model = args.model
    config.test_timeout = args.timeout

    if args.api_key:
        config.api_key = args.api_key
    if args.base_url:
        config.base_url = args.base_url
    if args.project_root:
        config.project_root = args.project_root
    if args.pytest_args:
        config.pytest_args = args.pytest_args

    # Parse process definitions
    if args.process:
        for proc_str in args.process:
            parts = proc_str.split(":")
            name = parts[0]
            port = int(parts[1]) if len(parts) > 1 and parts[1] else None
            log_file = parts[2] if len(parts) > 2 and parts[2] else None
            config.processes.append(ProcessConfig(
                name=name,
                debugpy_port=port,
                log_file=log_file,
            ))

    # Run
    orchestrator = Orchestrator(config)
    result = orchestrator.run()

    # Print summary
    print("\n" + "=" * 60)
    print("[hallucifix] SESSION SUMMARY")
    print("=" * 60)
    print(f"  Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  Iterations: {result.iterations}")
    print(f"  Fix attempts: {len(result.fix_attempts)}")

    if result.fix_attempts:
        print("\n  Applied fixes:")
        for att in result.fix_attempts:
            status = "WORKED" if att.success else "applied"
            print(f"    [{att.iteration}] {att.file_path} - {att.analysis[:60]}... ({status})")

    if not result.success and result.final_test_result:
        print(f"\n  Final test output (last 20 lines):")
        for line in result.final_test_result.raw_output.split("\n")[-20:]:
            print(f"    {line}")

    return 0 if result.success else 1


def _load_config_file(path: str) -> HallucifixConfig:
    """Load configuration from a JSON file."""
    with open(path) as f:
        data = json.load(f)

    processes = []
    for p in data.get("processes", []):
        processes.append(ProcessConfig(
            name=p["name"],
            pid=p.get("pid"),
            debugpy_port=p.get("debugpy_port"),
            log_file=p.get("log_file"),
        ))

    return HallucifixConfig(
        test_path=data.get("test_path", ""),
        processes=processes,
        project_root=data.get("project_root"),
        max_fix_iterations=data.get("max_iterations", 5),
        model=data.get("model", "gpt-4o"),
        api_key=data.get("api_key"),
        base_url=data.get("base_url"),
        pytest_args=data.get("pytest_args", []),
        test_timeout=data.get("timeout", 120.0),
    )


if __name__ == "__main__":
    sys.exit(main())
