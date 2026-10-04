import unittest

from rx7900xtx_bench.workloads import build_prompt_tokens, common_suffix, load_fixtures


class FakeClient:
    def apply_template(self, messages):
        return "|".join(message["content"] for message in messages)

    def tokenize(self, content, add_special=True):
        if "|" in content:
            return list(range(100)) + [900, 901]
        return [900, 901]


class WorkloadsTest(unittest.TestCase):
    def test_common_suffix_preserves_template_tail(self):
        self.assertEqual(common_suffix([1, 2, 3, 4], [9, 3, 4]), [3, 4])

    def test_common_suffix_rejects_unrelated_sequences(self):
        with self.assertRaises(RuntimeError):
            common_suffix([1, 2], [3, 4])

    def test_manifest_fixtures_build_exact_depth_tokens(self):
        fixtures = load_fixtures()

        tokens, token_hash = build_prompt_tokens(FakeClient(), fixtures["code-review-v1"], 16)

        self.assertEqual(len(fixtures), 3)
        self.assertEqual(len(tokens), 16)
        self.assertEqual(len(token_hash), 64)


if __name__ == "__main__":
    unittest.main()
