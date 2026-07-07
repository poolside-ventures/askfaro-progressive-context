"""A5: branch-descriptor synthesis reads descendant content, not child descriptors."""

import json

from askfaro_progressive_context.build.descriptors import LLMDescriptorModel, _descendant_content
from askfaro_progressive_context.build.ir import SourceNode


class _EchoClient:
    """Captures the last prompt and returns a valid descriptor JSON."""

    def __init__(self):
        self.last_prompt = None

    def complete(self, prompt, system=None, response_format=None):
        self.last_prompt = prompt
        return json.dumps({"what": "synthesized", "when": "synth", "keywords": ["k"]})


def _branch():
    return SourceNode(
        id="grp",
        title="scheduling",
        children=[
            SourceNode(id="a", title="recurring", content="RECURRING_MARKER create a repeating booking"),
            SourceNode(id="b", title="oneoff", content="ONEOFF_MARKER create a single booking"),
        ],
    )


def test_descendant_content_covers_every_child():
    text = _descendant_content(_branch(), max_chars=4000)
    assert "RECURRING_MARKER" in text and "ONEOFF_MARKER" in text


def test_synthesis_branch_prompt_uses_content_not_just_descriptors():
    client = _EchoClient()
    model = LLMDescriptorModel(client, synthesis=True)
    d = model.describe_branch(_branch(), children=[])
    assert d.what == "synthesized"
    assert "RECURRING_MARKER" in client.last_prompt  # verbatim content reached the prompt
    assert "SYNTHESIZES" in client.last_prompt


def test_non_synthesis_branch_prompt_uses_child_descriptors():
    from askfaro_progressive_context.build.descriptors import Descriptor

    client = _EchoClient()
    model = LLMDescriptorModel(client, synthesis=False)
    model.describe_branch(_branch(), children=[Descriptor("child what", "child when", [])])
    assert "child what" in client.last_prompt
    assert "RECURRING_MARKER" not in client.last_prompt
