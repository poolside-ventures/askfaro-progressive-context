import json
from pathlib import Path

import pytest

from askfaro_progressive_context import Manifest

EXAMPLES = Path(__file__).parents[1] / "examples" / "skills"


@pytest.fixture
def manifest_dict() -> dict:
    return json.loads((EXAMPLES / "manifest.pcx.4k.json").read_text())


@pytest.fixture
def manifest(manifest_dict) -> Manifest:
    return Manifest.from_dict(manifest_dict)


@pytest.fixture
def cases() -> list[dict]:
    return json.loads((EXAMPLES / "cases.json").read_text())
