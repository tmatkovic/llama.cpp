import unittest

from rx7900xtx_bench.cli import parse_args, resolve_depths, resolve_mtp_n_max_values, resolved_options
from rx7900xtx_bench.config import resolve_config


class CliTest(unittest.TestCase):
    def test_depths_accepts_suite_values(self):
        args = parse_args(["--depths", "16384,32768"])

        self.assertEqual(resolve_depths(args), [16384, 32768])

    def test_quick_is_default_suite(self):
        args = parse_args([])

        self.assertEqual(args.suite, "quick")
        self.assertEqual(resolve_depths(args), [16384])

    def test_rejects_4k_depth(self):
        with self.assertRaisesRegex(ValueError, "16384,32768"):
            resolve_depths(parse_args(["--depth", "4096"]))

    def test_mtp_sweep_accepts_unique_values(self):
        args = parse_args(["--mtp-sweep", "1,2,4,8"])

        self.assertEqual(resolve_mtp_n_max_values(args, resolve_config("qwen35-iq3s", {})), [1, 2, 4, 8])

    def test_mtp_sweep_rejects_duplicate_values(self):
        args = parse_args(["--mtp-sweep", "1,1"])

        with self.assertRaisesRegex(ValueError, "unique positive"):
            resolve_mtp_n_max_values(args, resolve_config("qwen35-iq3s", {}))


if __name__ == "__main__":
    unittest.main()
