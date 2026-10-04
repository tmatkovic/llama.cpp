import unittest

from rx7900xtx_bench.config import resolve_config, set_mtp_n_max


class ConfigTest(unittest.TestCase):
    def test_local_values_override_preset(self):
        config = resolve_config("qwen35-iq3s", {"model": "/tmp/model.gguf", "server": "/tmp/llama-server"})
        self.assertEqual(config["context_size"], 200000)
        self.assertEqual(config["model"], "/tmp/model.gguf")
        self.assertIn("--spec-type", config["server_args"])

    def test_local_config_cannot_replace_pinned_server_settings(self):
        with self.assertRaisesRegex(ValueError, "server_args"):
            resolve_config("qwen35-iq3s", {"server_args": ["--spec-type", "none"]})

    def test_mtp_n_max_override_preserves_preset(self):
        config = resolve_config("qwen35-iq3s", {})
        result = set_mtp_n_max(config, 8)

        index = result["server_args"].index("--spec-draft-n-max")
        self.assertEqual(result["server_args"][index + 1], "8")
        self.assertEqual(config["server_args"][index + 1], "2")


if __name__ == "__main__":
    unittest.main()
