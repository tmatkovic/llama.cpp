from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
from typing import Any

from .metrics import counter_deltas, server_generation_metrics, summarize_sample_groups, summarize_samples
from .process import ServerProcess
from .server_client import ServerClient
from .workloads import Fixture, build_prompt_tokens


def build_server_command(config: dict[str, Any], host: str, port: int) -> list[str]:
    command = [str(config["server"]), "--model", str(config["model"]), "--host", host, "--port", str(port), "--metrics", "--no-warmup"]
    if config.get("mmproj"):
        command.extend(["--mmproj", str(config["mmproj"])])
    command.extend(str(value) for value in config["server_args"])
    return command


def run_benchmark(config: dict[str, Any], options: dict[str, Any], fixture: Fixture) -> Path:
    depth = options["depth"]
    if depth not in config["depths"]:
        raise ValueError(f"depth {depth} is not in the preset workload matrix")
    results_dir = make_results_dir(Path(options["results_dir"]), options["label"])
    logs_dir, responses_dir = results_dir / "logs", results_dir / "responses"
    responses_dir.mkdir(parents=True)
    command = build_server_command(config, options["host"], options["port"])
    require_port_available(options["host"], options["port"])
    manifest = make_manifest(config, options, command, fixture)
    manifest["device_inventory"] = verify_requested_device(config)
    write_json(results_dir / "manifest.json", manifest)

    client = ServerClient(options["host"], options["port"], options["timeout_seconds"])
    server = ServerProcess(command, logs_dir / "server.log")
    samples: list[dict[str, Any]] = []
    try:
        server.start()
        server.wait_ready(client, options["startup_timeout_seconds"])
        server.wait_mtp(options["startup_timeout_seconds"])
        manifest["runtime"]["context_effective"] = verify_server_configuration(client, config)
        prompt_tokens, prompt_hash = build_prompt_tokens(client, fixture, depth)
        manifest["prompt"] = {
            "fixture_id": fixture.id,
            "fixture_category": fixture.category,
            "fixture_source": fixture.source,
            "fixture_text_sha256": fixture.text_sha256,
            "requested_depth": depth,
            "observed_depth": len(prompt_tokens),
            "token_sha256": prompt_hash,
        }

        effective_mode = options["prompt_mode"]
        capability: dict[str, Any] | None = None
        if effective_mode == "reused-prefix":
            capability, probe_responses = probe_prefix_reuse(client, prompt_tokens, options["output_tokens"])
            for name, response in probe_responses.items():
                write_json(responses_dir / f"capability-{name}.json", response)
            if not capability["supported"]:
                effective_mode = "fresh-fallback"
        manifest["prompt_mode"] = {
            "requested": options["prompt_mode"],
            "effective": effective_mode,
            "prefix_reuse_capability": capability,
        }
        write_json(results_dir / "manifest.json", manifest)

        for index in range(options["warmup"]):
            warmup = measure_request(client, prompt_tokens, options["output_tokens"], f"warmup-{index}", effective_mode, fixture.id, depth)
            warmup["requested_prompt_mode"] = options["prompt_mode"]
            warmup["fixture_text_sha256"] = fixture.text_sha256
            warmup["prompt_token_sha256"] = prompt_hash
            write_json(responses_dir / f"warmup-{index}.json", warmup.pop("raw_response"))
            warmup["warmup"] = True
            append_jsonl(results_dir / "warmups.jsonl", warmup)
        for index in range(options["runs"]):
            sample_id = f"sample-{index:03d}"
            sample = measure_request(client, prompt_tokens, options["output_tokens"], sample_id, effective_mode, fixture.id, depth)
            sample["requested_prompt_mode"] = options["prompt_mode"]
            sample["fixture_text_sha256"] = fixture.text_sha256
            sample["prompt_token_sha256"] = prompt_hash
            write_json(responses_dir / f"{sample_id}.json", sample.pop("raw_response"))
            samples.append(sample)
            append_jsonl(results_dir / "samples.jsonl", sample)
    finally:
        server.stop()

    summary = summarize_samples(samples)
    summary.update({"preset": options["preset"], "fixture_id": fixture.id, "depth": depth, "prompt_mode": effective_mode, "runs": options["runs"], "output_tokens_requested": options["output_tokens"]})
    summary["groups"] = summarize_sample_groups(samples)
    write_json(results_dir / "summary.json", summary)
    write_csv(results_dir / "summary.csv", samples)
    write_report(results_dir / "report.md", summary, manifest)
    return results_dir


def probe_prefix_reuse(client: ServerClient, prompt_tokens: list[int], output_tokens: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    probe_tokens = min(output_tokens, 16)
    fresh = measure_request(client, prompt_tokens, probe_tokens, "capability-fresh", "fresh", "capability", len(prompt_tokens), return_tokens=True, seed=1234)
    prepare = completion_response(client, {"prompt": prompt_tokens, "n_predict": 0, "stream": True, "timings_per_token": True, "cache_prompt": False})
    reused = measure_request(client, prompt_tokens, probe_tokens, "capability-reused", "reused-prefix", "capability", len(prompt_tokens), return_tokens=True, seed=1234)
    fresh_tokens = fresh["raw_response"].get("tokens")
    reused_tokens = reused["raw_response"].get("tokens")
    evaluated = reused["prompt_eval_tokens"]
    supported = (
        isinstance(evaluated, int)
        and evaluated < len(prompt_tokens)
        and isinstance(fresh_tokens, list)
        and fresh_tokens == reused_tokens
    )
    reason = None if supported else "reused prefix did not preserve deterministic output or reduce prompt evaluation"
    return {
        "supported": supported,
        "reason": reason,
        "fresh_prompt_eval_tokens": fresh["prompt_eval_tokens"],
        "reused_prompt_eval_tokens": evaluated,
        "reused_prompt_tokens": reused["prompt_reused_tokens"],
        "probe_output_tokens": probe_tokens,
    }, {"fresh": fresh["raw_response"], "prepare": prepare, "reused": reused["raw_response"]}


def completion_response(client: ServerClient, body: dict[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] | None = None
    for _, event in client.completion_stream(body):
        if event.get("stop") is True:
            response = event
    if response is None:
        raise RuntimeError("stream completed without a final completion response")
    return response


def measure_request(client: ServerClient, prompt_tokens: list[int], output_tokens: int, sample_id: str, prompt_mode: str = "fresh", fixture_id: str = "unknown", depth: int | None = None, return_tokens: bool = False, seed: int | None = None) -> dict[str, Any]:
    metrics_before = client.metrics()
    request_started, first_content_time = time.monotonic(), None
    final_response: dict[str, Any] | None = None
    body = {"prompt": prompt_tokens, "n_predict": output_tokens, "stream": True, "timings_per_token": True, "cache_prompt": prompt_mode == "reused-prefix", "return_tokens": return_tokens, "ignore_eos": True}
    if seed is not None:
        body["seed"] = seed
    for event_time, event in client.completion_stream(body):
        if first_content_time is None and (event.get("content") or event.get("tokens")):
            first_content_time = event_time
        if event.get("stop") is True:
            final_response = event
    request_finished, metrics_after = time.monotonic(), client.metrics()
    if final_response is None:
        raise RuntimeError("stream completed without a final completion response")
    final_output_tokens = final_response.get("tokens_predicted")
    if not isinstance(final_output_tokens, int):
        raise RuntimeError("completion response has no authoritative final token count")
    timings = final_response.get("timings")
    if not isinstance(timings, dict):
        raise RuntimeError("completion response has no server timings")
    generation_metrics = server_generation_metrics(timings, final_output_tokens)
    deltas = counter_deltas(metrics_before, metrics_after)
    draft_proposed = deltas["llamacpp:spec_decode_num_draft_tokens_total"]
    draft_accepted = deltas["llamacpp:spec_decode_num_accepted_tokens_total"]
    draft_steps = deltas["llamacpp:spec_decode_num_drafts_total"]
    if draft_proposed is None or draft_proposed <= 0 or draft_steps is None or draft_steps <= 0:
        raise RuntimeError("scored request did not record active MTP drafting and verification")
    request_seconds = request_finished - request_started
    delivery_seconds = request_finished - first_content_time if first_content_time is not None else None
    prompt_eval = timings.get("prompt_n")
    if not isinstance(prompt_eval, int):
        prompt_eval = None
    prompt_reused = timings.get("cache_n")
    if not isinstance(prompt_reused, int):
        prompt_reused = None
    return {
        "sample_id": sample_id, "warmup": False, "fixture_id": fixture_id, "requested_depth": depth or len(prompt_tokens), "observed_depth": len(prompt_tokens), "requested_prompt_mode": prompt_mode, "effective_prompt_mode": prompt_mode,
        "output_tokens_requested": output_tokens, "final_output_tokens": final_output_tokens, "output_completed": final_output_tokens >= output_tokens, "stop_type": final_response.get("stop_type"), "stopping_word": final_response.get("stopping_word"), "request_ms": request_seconds * 1000.0, "ttft_ms": None if first_content_time is None else (first_content_time - request_started) * 1000.0,
        "end_to_end_output_tps": final_output_tokens / request_seconds if request_seconds > 0 else None, "client_delivery_tps": final_output_tokens / delivery_seconds if delivery_seconds and delivery_seconds > 0 else None,
        **generation_metrics, "prompt_eval_tokens": prompt_eval, "prompt_reused_tokens": prompt_reused, "prompt_tps": timings.get("prompt_per_second"),
        "draft_proposed": draft_proposed, "draft_accepted": draft_accepted, "draft_acceptance": draft_accepted / draft_proposed if draft_accepted is not None else None, "draft_steps": draft_steps, "raw_response": final_response,
    }


def context_size_effective(context_size: int) -> int:
    return ((context_size + 255) // 256) * 256


def verify_requested_device(config: dict[str, Any]) -> str:
    inventory = command_output([str(config["server"]), "--list-devices"])
    if inventory is None or "Vulkan0" not in inventory or "7900 XTX" not in inventory:
        raise RuntimeError("llama-server --list-devices did not confirm RX 7900 XTX as Vulkan0")
    return inventory


def verify_server_configuration(client: ServerClient, config: dict[str, Any]) -> int:
    props = client.props()
    settings = props.get("default_generation_settings")
    expected_context = context_size_effective(config["context_size"])
    if not isinstance(settings, dict) or settings.get("n_ctx") != expected_context:
        raise RuntimeError(f"llama-server context is {settings.get('n_ctx') if isinstance(settings, dict) else None}, expected {expected_context}")
    if props.get("total_slots") != 1:
        raise RuntimeError(f"llama-server has {props.get('total_slots')} slots, expected 1")
    if not isinstance(props.get("model_path"), str) or Path(props["model_path"]).resolve() != Path(config["model"]).resolve():
        raise RuntimeError("llama-server reported a different model path")
    return expected_context


def make_manifest(config: dict[str, Any], options: dict[str, Any], command: list[str], fixture: Fixture) -> dict[str, Any]:
    model_path = Path(config["model"])
    return {"schema_version": 2, "created_utc": datetime.now(UTC).isoformat(), "preset": options["preset"], "model": {"path": str(model_path), "filename": model_path.name, "size_bytes": model_path.stat().st_size, "sha256": file_sha256(model_path)}, "fixture": {"id": fixture.id, "category": fixture.category, "source": fixture.source, "license": fixture.license, "text_sha256": fixture.text_sha256}, "server_command": command, "resolved_config": config, "runtime": {"host": options["host"], "port": options["port"], "context_requested": config["context_size"], "context_effective_expected": context_size_effective(config["context_size"]), "runs": options["runs"], "warmup": options["warmup"], "output_tokens": options["output_tokens"]}, "server_version": command_output([str(config["server"]), "--version"]), "source_revision": command_output(["git", "rev-parse", "HEAD"])}


def require_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_client:
        if socket_client.connect_ex((host, port)) == 0:
            raise RuntimeError(f"refusing to use occupied port {host}:{port}")


def make_results_dir(root: Path, label: str) -> Path:
    safe_label = "".join(char if char.isalnum() or char in "-_" else "-" for char in label)
    path = root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{safe_label}"
    path.mkdir(parents=True)
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, sort_keys=True))
        file.write("\n")


def write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    import csv
    if samples:
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(samples[0]))
            writer.writeheader()
            writer.writerows(samples)


def write_report(path: Path, summary: dict[str, Any], manifest: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("# RX 7900 XTX MTP benchmark\n\n")
        file.write(f"- Fixture: `{summary['fixture_id']}`\n- Prompt depth: {summary['depth']}\n- Prompt mode: `{summary['prompt_mode']}`\n- Measured runs: {summary['runs']}\n")
        file.write(f"- Model SHA-256: `{manifest['model']['sha256']}`\n\n")
        runtime = manifest["runtime"]
        file.write(f"- Context requested: {runtime['context_requested']} tokens\n- Context effective: {runtime.get('context_effective', runtime['context_effective_expected'])} tokens\n\n")
        for label, key, unit in (("MTP final output throughput", "mtp_output_tps", "tokens/s"), ("End-to-end final output throughput", "end_to_end_output_tps", "tokens/s"), ("Client delivery throughput", "client_delivery_tps", "tokens/s"), ("TTFT", "ttft_ms", "ms"), ("Request time", "request_ms", "ms"), ("Draft acceptance", "draft_acceptance", "ratio")):
            values = summary[key]
            file.write(f"## {label}\n\n- Count: {values['count']}\n- Mean: {values['mean']} {unit}\n- Median: {values['median']} {unit}\n- Standard deviation: {values['stdev']} {unit}\n\n")
