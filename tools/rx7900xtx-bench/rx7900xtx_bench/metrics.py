from __future__ import annotations

from statistics import mean, median, stdev
from typing import Any


COUNTERS = (
    "llamacpp:spec_decode_num_draft_tokens_total",
    "llamacpp:spec_decode_num_accepted_tokens_total",
    "llamacpp:spec_decode_num_drafts_total",
)


def server_generation_metrics(timings: dict[str, Any], final_output_tokens: int) -> dict[str, float | int]:
    predicted_n = timings.get("predicted_n")
    predicted_ms = timings.get("predicted_ms")
    predicted_tps = timings.get("predicted_per_second")
    if not isinstance(predicted_n, int) or isinstance(predicted_n, bool):
        raise RuntimeError("completion response has no valid server predicted_n")
    if predicted_n != final_output_tokens:
        raise RuntimeError(
            f"server predicted_n {predicted_n} does not match final output token count {final_output_tokens}"
        )
    if not is_positive_number(predicted_ms):
        raise RuntimeError("completion response has no positive server predicted_ms")
    if not is_nonnegative_number(predicted_tps):
        raise RuntimeError("completion response has no valid server predicted_per_second")
    return {
        "server_generation_ms": float(predicted_ms),
        "server_predicted_n": predicted_n,
        "server_predicted_tps": float(predicted_tps),
        "mtp_output_tps": final_output_tokens / (float(predicted_ms) / 1000.0),
    }


def counter_deltas(before: dict[str, float], after: dict[str, float]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for name in COUNTERS:
        result[name] = after[name] - before[name] if name in before and name in after else None
    return result


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_sample_group(samples)


def summarize_sample_groups(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for sample in samples:
        key = (str(sample["fixture_id"]), int(sample["observed_depth"]), str(sample["effective_prompt_mode"]))
        groups.setdefault(key, []).append(sample)
    return [
        {
            "fixture_id": fixture_id,
            "depth": depth,
            "prompt_mode": prompt_mode,
            **summarize_sample_group(group_samples),
        }
        for (fixture_id, depth, prompt_mode), group_samples in sorted(groups.items())
    ]


def summarize_sample_group(samples: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = (
        "mtp_output_tps",
        "end_to_end_output_tps",
        "client_delivery_tps",
        "ttft_ms",
        "request_ms",
        "prompt_eval_tokens",
        "prompt_reused_tokens",
        "draft_acceptance",
    )
    summary: dict[str, Any] = {"sample_count": len(samples)}
    for name in metrics:
        values = [float(sample[name]) for sample in samples if sample.get(name) is not None]
        summary[name] = summarize_values(values)
    return summary


def summarize_values(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "stdev": None}
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "stdev": stdev(values) if len(values) > 1 else 0.0,
    }


def is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def is_nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
