# RX 7900 XTX Vulkan MTP progress

Status: initial benchmark baseline complete. No Vulkan optimization code has been added.

## Confirmed environment

- Source revision: `0f0796f9076f3ebd3f49fa9be74598b33c42aada`
- Server: `0.5.0-dev` build `11380`, GCC `16.2.1`
- GPU: `Vulkan0`, AMD Radeon RX 7900 XTX, RADV NAVI31
- Model: `Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`
- Model SHA-256: `9aecf1cd41b2cb2f32a74e0d889e33855ebef43b26f43b43feb5720239e677e5`
- Requested context: 200000 tokens
- Effective context: 200192 tokens after upstream 256-token alignment

## Initial MTP baseline

Run directory: `bench-results/20261003T182056Z-iq3s-quick-baseline/` (local and ignored)

- Workload: project-authored chat fixture, 4096 prompt tokens, 512 output tokens
- Mode: fresh requests with `--no-cache-prompt`
- Server: one loopback slot, `Vulkan0`, all GPU layers, Q8_0 K/V cache, Flash Attention, `draft-mtp`, `n-max=4`
- Warmup: 1 request, excluded from scores
- Measured requests: 5, all completed with 512 final output tokens
- MTP: active; startup created the MTP draft context and each request reported draft acceptance

| Metric | Result |
|---|---:|
| Client end-to-end output TPS, mean | 40.87 |
| Client end-to-end output TPS, median | 41.97 |
| Client delivery TPS, mean | 67.06 |
| Client delivery TPS, median | 69.54 |
| Client TTFT, mean | 4829.09 ms |
| Server predicted TPS, mean | 66.94 |
| Server predicted TPS, median | 69.41 |
| Draft proposed | 3634 |
| Draft accepted | 1644 |
| Weighted draft acceptance | 45.24% |

Server timing semantics were validated against the pinned source. `predicted_ms` spans post-prompt generation through the final synchronized MTP step, including draft, verification, acceptance, and commit work. The runner's authoritative `mtp_output_tps` is `tokens_predicted / (predicted_ms / 1000)`. Raw `predicted_per_second` remains recorded, but upstream excludes the first output token from its numerator.

The slot-selection log can report LCP similarity on later requests. This is not prefix reuse in this run: `--no-cache-prompt` disables reuse of prior prompt evaluation, and every measured request evaluated all 4096 prompt tokens.

## MTP n-max screening

Run directories: `bench-results/20261004T085923Z-iq3s-nmax-screening-depth4096-nmax1/` through `bench-results/20261004T091004Z-iq3s-nmax-screening-depth16384-nmax8/`, plus `20261004T091607Z-iq3s-nmax-screening-depth4096-nmax3/` and `20261004T091705Z-iq3s-nmax-screening-depth16384-nmax3/` (local and ignored).

- Workload: project-authored chat fixture, fresh requests, 512 output tokens
- Depths: 4096 and 16384 prompt tokens with allocated context of 200000 tokens
- Candidates: `n-max=1,2,4,8`
- Each combination: 1 excluded warmup and 3 measured requests

| Depth | n-max | MTP output TPS mean | TTFT mean | Weighted draft acceptance |
|---:|---:|---:|---:|---:|
| 4096 | 1 | 68.52 | 4813.93 ms | 77.40% |
| 4096 | 2 | 76.25 | 4833.89 ms | 67.18% |
| 4096 | 3 | 69.95 | 4845.08 ms | 51.61% |
| 4096 | 4 | 70.11 | 4874.23 ms | 46.95% |
| 4096 | 8 | 29.59 | 4869.14 ms | 32.29% |
| 16384 | 1 | 64.97 | 20222.74 ms | 80.74% |
| 16384 | 2 | 68.91 | 20234.82 ms | 65.11% |
| 16384 | 3 | 68.17 | 20306.74 ms | 57.31% |
| 16384 | 4 | 66.06 | 20365.61 ms | 50.34% |
| 16384 | 8 | 26.60 | 20461.39 ms | 29.32% |

`n-max=2` is the screening winner at both primary depths and is frozen in the benchmark preset for fixed-setting kernel A/B comparisons. This three-run screening does not replace broader validation of the selected setting.

## Benchmark runner status

Implemented and tested:

- owned loopback server launch, readiness, log capture, and owned-process cleanup
- pinned IQ3_S server configuration and resolved argv dry run
- model hash, device inventory, model path, context, slot count, and MTP startup checks
- chat-template prompt construction with exact token depth and token hash
- warmup, five measured fresh requests, raw responses, manifests, JSONL, CSV, JSON, and Markdown report
- authoritative final output token count, client timings, raw server timings, and speculative counter deltas
- unit tests for configuration, metrics, process cleanup, report generation, context alignment, SSE parsing, and prompt suffix handling

## Next work

1. Profile the measured serving path before proposing any Vulkan kernel or graph change.
2. Add the smallest measured optimization and compare same-commit control and optimized builds.
