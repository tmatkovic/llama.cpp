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
from .workloads import load_fixtures


SUITES = {
    "quick": {"depths": [16384], "fixtures": ["chat-planning-v1"], "runs": 3},
    "common": {"depths": [32768], "fixtures": ["chat-planning-v1", "chat-debugging-v1", "code-review-v1"], "runs": 3},
    "full": {"depths": [32768], "fixtures": ["chat-planning-v1", "chat-debugging-v1", "code-review-v1"], "runs": 3},
}
SUITE_DEPTHS = {16384, 32768}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RX 7900 XTX single-user MTP benchmark")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="qwen35-iq3s")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--mmproj", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--suite", choices=sorted(SUITES), default="quick")
    depths = parser.add_mutually_exclusive_group()
    depths.add_argument("--depth", type=int)
    depths.add_argument("--depths")
    parser.add_argument("--runs", type=int)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--output-tokens", type=int, default=512)
    parser.add_argument("--prompt-mode", choices=("fresh", "reused-prefix"), default="reused-prefix")
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
    for name in ("model", "server", "mmproj"):
        value = getattr(args, name)
        if value is not None:
            config[name] = str(value)
    missing = [name for name in ("model", "server") if not config.get(name)]
    if missing:
        raise ValueError(f"missing required local configuration: {', '.join(missing)}")
    for name in ("model", "server", "mmproj"):
        if config.get(name) and not Path(config[name]).is_file():
            raise ValueError(f"{name} does not exist: {config[name]}")
    if args.warmup < 0 or args.output_tokens <= 0 or (args.runs is not None and args.runs <= 0):
        raise ValueError("--warmup must be non-negative and --runs/--output-tokens must be positive")
    if args.host != "127.0.0.1":
        raise ValueError("--host must be 127.0.0.1; benchmark servers run only on loopback")
    suite = SUITES[args.suite]
    options = {
        "preset": args.preset, "suite": args.suite, "depths": resolve_depths(args), "fixture_ids": suite["fixtures"],
        "mtp_n_max_values": resolve_mtp_n_max_values(args, config), "runs": args.runs if args.runs is not None else suite["runs"], "warmup": args.warmup,
        "output_tokens": args.output_tokens, "prompt_mode": args.prompt_mode, "host": args.host, "port": args.port,
        "timeout_seconds": args.timeout_seconds, "startup_timeout_seconds": args.startup_timeout_seconds,
        "results_dir": str(args.results_dir), "label": args.label,
    }
    return config, options


def resolve_depths(args: argparse.Namespace) -> list[int]:
    if args.depths is None:
        depths = [args.depth] if args.depth is not None else SUITES[args.suite]["depths"]
    else:
        try:
            depths = [int(value) for value in args.depths.split(",")]
        except ValueError as error:
            raise ValueError("--depths must be a comma-separated list of integers") from error
    if not depths or len(set(depths)) != len(depths) or any(depth not in SUITE_DEPTHS for depth in depths):
        raise ValueError("benchmark depths must be unique values from 16384,32768; populated prompts never exceed 32768")
    return depths


def resolve_mtp_n_max_values(args: argparse.Namespace, config: dict[str, Any]) -> list[int]:
    if args.mtp_sweep is None:
        return [args.mtp_n_max] if args.mtp_n_max is not None else [2]
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
        fixtures = load_fixtures()
        plans = []
        for depth in options["depths"]:
            for fixture_id in options["fixture_ids"]:
                for n_max in options["mtp_n_max_values"]:
                    plans.append({"depth": depth, "fixture_id": fixture_id, "mtp_n_max": n_max, "command": build_server_command(set_mtp_n_max(config, n_max), options["host"], options["port"])})
        if args.dry_run:
            print(json.dumps({"plans": plans, "config": config, "options": options}, indent=2))
            return
        for plan in plans:
            run_options = deepcopy(options)
            run_options.update(plan)
            run_options["label"] = f"{options['label']}-{plan['fixture_id']}-depth{plan['depth']}-nmax{plan['mtp_n_max']}-{options['prompt_mode']}"
            result_path = run_benchmark(set_mtp_n_max(config, plan["mtp_n_max"]), run_options, fixtures[plan["fixture_id"]])
            print(f"results: {result_path}")
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"rx7900xtx-bench: {error}", file=sys.stderr)
        raise SystemExit(2) from error
