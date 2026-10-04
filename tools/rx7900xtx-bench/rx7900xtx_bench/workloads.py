from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .server_client import ServerClient


PROMPTS_DIR = Path(__file__).with_name("prompts")


@dataclass(frozen=True)
class Fixture:
    id: str
    category: str
    source: str
    license: str
    text: str
    text_sha256: str
    construction: str
    intended_task: str


def load_fixtures() -> dict[str, Fixture]:
    with (PROMPTS_DIR / "manifest.json").open(encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("fixtures"), list):
        raise RuntimeError("prompt fixture manifest is invalid")

    fixtures: dict[str, Fixture] = {}
    for item in manifest["fixtures"]:
        if not isinstance(item, dict):
            raise RuntimeError("prompt fixture manifest contains an invalid fixture")
        fixture_id = item.get("id")
        relative_path = item.get("path")
        if not isinstance(fixture_id, str) or not isinstance(relative_path, str):
            raise RuntimeError("prompt fixture manifest has no fixture ID or path")
        path = PROMPTS_DIR / relative_path
        text = path.read_text(encoding="utf-8")
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_sha256 != item.get("text_sha256"):
            raise RuntimeError(f"prompt fixture text hash does not match manifest: {fixture_id}")
        fixtures[fixture_id] = Fixture(
            id=fixture_id,
            category=required_string(item, "category", fixture_id),
            source=required_string(item, "source", fixture_id),
            license=required_string(item, "license", fixture_id),
            text=text,
            text_sha256=text_sha256,
            construction=required_string(item, "construction", fixture_id),
            intended_task=required_string(item, "intended_task", fixture_id),
        )
    return fixtures


def required_string(item: dict[str, object], name: str, fixture_id: str) -> str:
    value = item.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"prompt fixture {fixture_id} has no {name}")
    return value


def build_prompt_tokens(client: ServerClient, fixture: Fixture, depth: int) -> tuple[list[int], str]:
    if depth <= 0:
        raise ValueError("prompt depth must be positive")
    question = f"Give a concise answer for the {fixture.intended_task}."
    repeats = max(1, (depth // 64) + 2)
    text = "\n".join(fixture.text for _ in range(repeats))
    tokens = client.tokenize(client.apply_template([
        {"role": "system", "content": text},
        {"role": "user", "content": question},
    ]), add_special=False)
    if len(tokens) < depth:
        raise RuntimeError(f"fixture only produced {len(tokens)} tokens for requested depth {depth}")
    suffix_tokens = client.tokenize(client.apply_template([
        {"role": "user", "content": question},
    ]), add_special=False)
    suffix = common_suffix(tokens, suffix_tokens)
    if len(suffix) >= depth:
        raise RuntimeError("chat-template suffix is too long for requested depth")
    selected = tokens[:depth - len(suffix)] + suffix
    return selected, token_sha256(selected)


def token_sha256(tokens: list[int]) -> str:
    return hashlib.sha256(",".join(str(token) for token in tokens).encode("ascii")).hexdigest()


def common_suffix(left: list[int], right: list[int]) -> list[int]:
    count = 0
    while count < len(left) and count < len(right) and left[-count - 1] == right[-count - 1]:
        count += 1
    if count == 0:
        raise RuntimeError("unable to preserve the chat generation suffix")
    return left[-count:]
