# RX 7900 XTX Vulkan MTP progress

Status: benchmark harness and baseline validation are complete for the current 16k/32k scope. `n-max=2` is validated at 32k and is fixed for kernel A/B tests. No Vulkan optimization code has been added.

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
- versioned prompt manifest with two project-authored chat fixtures and one project-authored code fixture; every fixture text and constructed token sequence has a SHA-256 record
- `quick` as the default suite: 16384 tokens, one chat fixture, one warmup, and three measured samples
- `common` and `full` suites: 32768 tokens, all three fixtures, one warmup, and three measured samples per fixture; `--runs` can increase the count later
- explicit `fresh` and `reused-prefix` modes; reused-prefix runs a deterministic cache capability probe and becomes `fresh-fallback` if the pinned server/model cannot prove safe same-prefix restoration after generation
- per-sample prompt token hash, actual evaluated/reused prompt tokens, MTP output TPS, TTFT, request time, acceptance, MTP counters, and raw response storage
- per-fixture/depth/effective-mode summaries with count, mean, median, and standard deviation; fresh and reused-prefix samples remain separate

## Completed 16k/32k benchmark validation

The following local, ignored result directories use server build `0.5.0-dev-11380`, primary model SHA-256 `9aecf1cd41b2cb2f32a74e0d889e33855ebef43b26f43b43feb5720239e677e5`, requested context 200000/effective context 200192, Q8_0 K/V cache, and MTP `n-max=2`. Each row has one excluded warmup and three measured samples. `ignore_eos=true` fixed output length at 512 tokens for every measured sample.

### 32k fresh `n-max=2` validation

Run directories: `bench-results/20261004T100841Z-nmax2-32k-validation-fixed-output-chat-planning-v1-depth32768-nmax2-fresh/` through `20261004T101609Z-nmax2-32k-validation-fixed-output-code-review-v1-depth32768-nmax2-fresh/`.

| Fixture | MTP output TPS mean | TTFT mean | Draft acceptance mean | Prompt evaluated/reused |
|---|---:|---:|---:|---:|
| `chat-planning-v1` | 60.14 | 44818.43 ms | 60.37% | 32768 / 0 |
| `chat-debugging-v1` | 58.04 | 44946.21 ms | 56.72% | 32768 / 0 |
| `code-review-v1` | 61.19 | 44959.46 ms | 62.42% | 32768 / 0 |

All samples completed with active MTP draft/verify counters. This validates `n-max=2` as the fixed setting for kernel A/B tests through 32768 populated prompt tokens.

### Quick 16k reused-prefix smoke test

Run directory: `bench-results/20261004T102011Z-quick-16k-fixed-output-chat-planning-v1-depth16384-nmax2-reused-prefix/`.

- MTP output TPS mean: 62.34
- TTFT mean: 194.38 ms
- Draft acceptance mean: 54.03%
- Prompt evaluated/reused: 4 / 16380 tokens
- The deterministic capability probe passed, so the pinned server/model safely restored the identical prefix after generation.

### Full 32k reused-prefix validation

Run directories: `bench-results/20261004T102138Z-full-32k-reused-prefix-chat-planning-v1-depth32768-nmax2-reused-prefix/` through `20261004T102608Z-full-32k-reused-prefix-code-review-v1-depth32768-nmax2-reused-prefix/`.

| Fixture | MTP output TPS mean | TTFT mean | Draft acceptance mean | Prompt evaluated/reused |
|---|---:|---:|---:|---:|
| `chat-planning-v1` | 60.34 | 254.74 ms | 60.87% | 4 / 32764 |
| `chat-debugging-v1` | 60.68 | 249.67 ms | 61.51% | 4 / 32764 |
| `code-review-v1` | 61.85 | 250.50 ms | 63.73% | 4 / 32764 |

All full-suite samples completed with 512 final output tokens and active MTP draft/verify counters. Prefix reuse is approved for this pinned model/server configuration at 16k and 32k.

## Raw result retention

Keep these final baseline directories until a later same-configuration control baseline replaces them:

- `bench-results/20261004T100841Z-nmax2-32k-validation-fixed-output-chat-planning-v1-depth32768-nmax2-fresh/`
- `bench-results/20261004T101224Z-nmax2-32k-validation-fixed-output-chat-debugging-v1-depth32768-nmax2-fresh/`
- `bench-results/20261004T101609Z-nmax2-32k-validation-fixed-output-code-review-v1-depth32768-nmax2-fresh/`
- `bench-results/20261004T102011Z-quick-16k-fixed-output-chat-planning-v1-depth16384-nmax2-reused-prefix/`
- `bench-results/20261004T102138Z-full-32k-reused-prefix-chat-planning-v1-depth32768-nmax2-reused-prefix/`
- `bench-results/20261004T102353Z-full-32k-reused-prefix-chat-debugging-v1-depth32768-nmax2-reused-prefix/`
- `bench-results/20261004T102608Z-full-32k-reused-prefix-code-review-v1-depth32768-nmax2-reused-prefix/`

The older 4k baseline and screening directories remain useful historical evidence but are not needed for the current 16k/32k A/B baseline. Failed or superseded runs, including the pre-`ignore_eos` quick run and the pre-fixed-output 32k validation, can be deleted. Deleting all raw result directories is possible because this document retains the summary, but it removes request-level evidence, exact manifests, and the ability to recheck an unexpected later comparison.

Run the same validation from the activated `.venv-bench` environment:

```bash
python -m rx7900xtx_bench --preset qwen35-iq3s --config bench.local.json \
  --suite common --prompt-mode fresh --mtp-n-max 2 --label nmax2-32k-validation
```

## Next work

1. **English:** Profile the validated 16k/32k MTP serving path, identify the dominant Vulkan operation or synchronization cost, and propose one minimal optimization with a measurable A/B hypothesis.
2. **Hrvatski:** Profiliraj validirani 16k/32k MTP serving put, utvrdi dominantnu Vulkan operaciju ili trošak sinkronizacije i predloži jednu minimalnu optimizaciju s mjerljivom A/B hipotezom.
