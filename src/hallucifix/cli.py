"""hallucifix CLI entry-point."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile

from hallucifix.config import HallucifixConfig, ProcessConfig
from hallucifix.orchestrator import Orchestrator


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hallucifix",
        description="Attach debuggers, run tests, and AI-fix failures in a loop.",
    )
    p.add_argument("test_path", help="Path to the test file / directory for pytest.")
    p.add_argument(
        "-p",
        "--process",
        action="append",
        default=[],
        metavar="NAME:PORT:LOGFILE",
        help="Process to monitor (may be repeated).",
    )
    p.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to a hallucifix JSON config file.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum fix iterations (default: 5).",
    )
    p.add_argument("--model", default="gpt-4o", help="LLM model name.")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL.")
    p.add_argument("--timeout", type=int, default=120, help="Pytest timeout in seconds.")
    p.add_argument("--project-root", default=".", help="Project root directory.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args, extra = parser.parse_known_args(argv)

    # ── Logging setup ─────────────────────────────────────────────
    # Console: only hallucifix.* messages at INFO (clean progress output).
    # File: everything (including openai/httpcore) at DEBUG for diagnostics.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Debug log file
    log_file = tempfile.NamedTemporaryFile(
        prefix="hallucifix_", suffix=".log", delete=False, mode="w"
    )
    file_handler = logging.FileHandler(log_file.name)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger.addHandler(file_handler)

    # Console handler – hallucifix.* only
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(logging.Filter("hallucifix"))
    root_logger.addHandler(console_handler)

    log = logging.getLogger("hallucifix.cli")
    log.info("Debug log: %s", log_file.name)

    if args.config:
        config = HallucifixConfig.from_file(args.config)
        # CLI overrides
        if args.test_path:
            config.test_path = args.test_path
    else:
        processes = [ProcessConfig.from_cli_string(s) for s in args.process]
        config = HallucifixConfig(
            test_path=args.test_path,
            processes=processes,
            project_root=args.project_root,
            max_fix_iterations=args.max_iterations,
            model=args.model,
            timeout=args.timeout,
            base_url=args.base_url,
        )

    config.extra_pytest_args = extra

    orch = Orchestrator(config)
    result = orch.run()

    if result.success:
        print(f"\n✅ Tests passed after {result.iterations} iteration(s).")
        if result.report:
            if result.report.patch_path:
                print(f"   Patch: {result.report.patch_path}")
            if result.report.markdown_path:
                print(f"   Report: {result.report.markdown_path}")
        sys.exit(0)
    else:
        print(f"\n❌ Tests still failing after {result.iterations} iteration(s).")
        sys.exit(1)


if __name__ == "__main__":
    main()
