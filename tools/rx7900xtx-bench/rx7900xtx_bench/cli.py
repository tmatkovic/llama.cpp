from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .config import PRESETS, load_config, resolve_config, set_mtp_n_max
from .runner import build_server_command, run_benchmark


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RX 7900 XTX single-user MTP benchmark")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="qwen35-iq3s")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--mmproj", type=Path)
    parser.add_argument("--config", type=Path)
    depths = parser.add_mutually_exclusive_group()
    depths.add_argument("--depth", type=int)
    depths.add_argument("--depths")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output-tokens", type=int, default=512)
    mtp = parser.add_mutually_exclusive_group()
    mtp.add_argument("--mtp-n-max", type=int)
    mtp.add_argument("--mtp-sweep")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--startup-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--results-dir", type=Path, default=Path("bench-results"))
    parser.add_argument("--label", default="iq3s-baseline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def resolved_options(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    config = resolve_config(args.preset, load_config(args.config))
    if args.model is not None:
        config["model"] = str(args.model)
    if args.server is not None:
        config["server"] = str(args.server)
    if args.mmproj is not None:
        config["mmproj"] = str(args.mmproj)
    missing = [name for name in ("model", "server") if not config.get(name)]
    if missing:
        raise ValueError(f"missing required local configuration: {', '.join(missing)}")
    if not Path(config["model"]).is_file():
        raise ValueError(f"model does not exist: {config['model']}")
    if not Path(config["server"]).is_file():
        raise ValueError(f"server does not exist: {config['server']}")
    if config.get("mmproj") and not Path(config["mmproj"]).is_file():
        raise ValueError(f"mmproj does not exist: {config['mmproj']}")
    if args.runs <= 0 or args.output_tokens <= 0:
        raise ValueError("--runs and --output-tokens must be positive")
    if args.host != "127.0.0.1":
        raise ValueError("--host must be 127.0.0.1; benchmark servers run only on loopback")
    options = {
        "preset": args.preset,
        "depths": resolve_depths(args),
        "mtp_n_max_values": resolve_mtp_n_max_values(args, config),
        "runs": args.runs,
        "output_tokens": args.output_tokens,
        "host": args.host,
        "port": args.port,
        "timeout_seconds": args.timeout_seconds,
        "startup_timeout_seconds": args.startup_timeout_seconds,
        "results_dir": str(args.results_dir),
        "label": args.label,
    }
    return config, options


def resolve_depths(args: argparse.Namespace) -> list[int]:
    if args.depths is None:
        return [4096 if args.depth is None else args.depth]
    try:
        depths = [int(value) for value in args.depths.split(",")]
    except ValueError as error:
        raise ValueError("--depths must be a comma-separated list of integers") from error
    if not depths or any(depth <= 0 for depth in depths) or len(set(depths)) != len(depths):
        raise ValueError("--depths must contain unique positive integers")
    return depths


def resolve_mtp_n_max_values(args: argparse.Namespace, config: dict[str, Any]) -> list[int]:
    if args.mtp_sweep is None:
        if args.mtp_n_max is not None:
            return [args.mtp_n_max]
        server_args = config["server_args"]
        index = server_args.index("--spec-draft-n-max")
        return [int(server_args[index + 1])]
    try:
        values = [int(value) for value in args.mtp_sweep.split(",")]
    except ValueError as error:
        raise ValueError("--mtp-sweep must be a comma-separated list of integers") from error
    if not values or any(value <= 0 for value in values) or len(set(values)) != len(values):
        raise ValueError("--mtp-sweep must contain unique positive integers")
    return values


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config, options = resolved_options(args)
        commands = []
        for depth in options["depths"]:
            for n_max in options["mtp_n_max_values"]:
                run_config = set_mtp_n_max(config, n_max)
                commands.append({
                    "depth": depth,
                    "mtp_n_max": n_max,
                    "command": build_server_command(run_config, options["host"], options["port"]),
                })
        if args.dry_run:
            print(json.dumps({"commands": commands, "config": config, "options": options}, indent=2))
            return
        for depth in options["depths"]:
            for n_max in options["mtp_n_max_values"]:
                run_config = set_mtp_n_max(config, n_max)
                run_options = deepcopy(options)
                run_options["depth"] = depth
                run_options["label"] = f"{options['label']}-depth{depth}-nmax{n_max}"
                result_path = run_benchmark(run_config, run_options)
                print(f"results: {result_path}")
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"rx7900xtx-bench: {error}", file=sys.stderr)
        raise SystemExit(2) from error
