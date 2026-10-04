from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rx7900xtx_bench.runner import (
    context_size_effective,
    measure_request,
    verify_requested_device,
    verify_server_configuration,
    write_report,
)


class FakeClient:
    def __init__(self, props):
        self._props = props

    def props(self):
        return self._props


class FakeRequestClient:
    def __init__(self, metrics):
        self.metrics_values = iter(metrics)

    def metrics(self):
        return next(self.metrics_values)

    def completion_stream(self, body):
        yield 1.0, {
            "content": "output",
            "tokens_predicted": 4,
            "stop": True,
            "timings": {
                "predicted_n": 4,
                "predicted_ms": 100.0,
                "predicted_per_second": 30.0,
                "prompt_n": 8,
                "prompt_per_second": 40.0,
            },
        }


class RunnerTest(unittest.TestCase):
    def test_server_configuration_requires_expected_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            model_path = directory_path / "model.gguf"
            model_path.touch()
            client = FakeClient({
                "default_generation_settings": {"n_ctx": 200192},
                "total_slots": 1,
                "model_path": str(model_path),
            })

            context_effective = verify_server_configuration(client, {
                "context_size": 200000,
                "model": str(model_path),
            })
            self.assertEqual(context_effective, 200192)

    def test_effective_context_rounds_up_to_256_tokens(self):
        self.assertEqual(context_size_effective(200000), 200192)

    @patch("rx7900xtx_bench.runner.command_output")
    def test_requested_device_requires_rx7900xtx_as_vulkan0(self, command_output):
        command_output.return_value = "Vulkan0: AMD Radeon RX 7900 XTX\n"
        inventory = verify_requested_device({"server": "/tmp/llama-server"})

        self.assertIn("Vulkan0", inventory)

    def test_report_uses_client_delivery_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.md"
            write_report(report_path, {
                "preset": "qwen35-iq3s",
                "depth": 4096,
                "runs": 5,
                "mtp_output_tps": {"mean": 12.0, "median": 11.0},
                "end_to_end_output_tps": {"mean": 11.0, "median": 10.0},
                "client_delivery_tps": {"mean": 10.0, "median": 9.0},
            }, {
                "model": {"sha256": "test"},
                "runtime": {
                    "context_requested": 200000,
                    "context_effective_expected": 200192,
                },
            })

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("MTP final output throughput", report)
            self.assertIn("Mean: 12.0 tokens/s", report)
            self.assertIn("End-to-end final output throughput", report)
            self.assertIn("Mean: 11.0 tokens/s", report)
            self.assertIn("Context effective: 200192 tokens", report)

    def test_measure_request_requires_mtp_drafting_and_verification(self):
        client = FakeRequestClient([{}, {}])

        with self.assertRaisesRegex(RuntimeError, "active MTP"):
            measure_request(client, [1, 2], 4, "sample-000")


if __name__ == "__main__":
    unittest.main()
