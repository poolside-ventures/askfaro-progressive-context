"""faro-progressive-context: compile any content into a tiered, budget-aware,
agent-navigable progressive-disclosure manifest, plus an expansion protocol."""

from .eval import CaseResult, EvalReport, NavCase, run_case, run_eval
from .llm import LLMClient, OpenAICompatibleClient
from .navigator import KeywordNavigator, LLMNavigator, Navigator
from .runtime import (
    VIEW_LEVELS,
    BudgetExceeded,
    FrontierEntry,
    LeafResolver,
    Runtime,
    SearchBackend,
    dict_resolver,
    render_descriptor,
)
from .session import LOCAL, REMOTE, ModeConfig, NavSession
from .tokenizer import make_tokenizer
from .types import PROTOCOL_USAGE, Manifest, Node, Payload, Variant, estimate_tokens
from .validate import schema_errors, structural_errors, validate

__version__ = "0.0.7"

__all__ = [
    "BudgetExceeded",
    "CaseResult",
    "EvalReport",
    "FrontierEntry",
    "KeywordNavigator",
    "LLMClient",
    "LLMNavigator",
    "LOCAL",
    "REMOTE",
    "LeafResolver",
    "Manifest",
    "ModeConfig",
    "NavCase",
    "NavSession",
    "Navigator",
    "Node",
    "OpenAICompatibleClient",
    "PROTOCOL_USAGE",
    "Payload",
    "Runtime",
    "SearchBackend",
    "VIEW_LEVELS",
    "Variant",
    "dict_resolver",
    "estimate_tokens",
    "make_tokenizer",
    "render_descriptor",
    "run_case",
    "run_eval",
    "schema_errors",
    "structural_errors",
    "validate",
]
