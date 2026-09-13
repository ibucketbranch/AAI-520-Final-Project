"""Command-line entry point for the investment committee.

Takes a stock symbol and, once the agents exist, will run the full research
flow for it. Today it loads the configuration and reports which keys are set
(names only, never values) so a teammate can verify their environment.
"""

from __future__ import annotations

import argparse

from investment_committee import __version__
from investment_committee.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="investment-committee",
        description="Multi-agent stock research (AAI-520 final team project).",
    )
    parser.add_argument("ticker", help="stock symbol to research, for example NFLX")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Argument list, or None to use sys.argv.

    Returns:
        Process exit code, 0 on success.
    """
    args = build_parser().parse_args(argv)
    settings = load_settings()
    print(f"Research for {args.ticker} is not implemented yet.")
    print("Configuration loaded. Key status (values are never printed):")
    for name in settings.present():
        print(f"  {name}: set")
    for name in settings.missing():
        print(f"  {name}: missing")
    return 0
