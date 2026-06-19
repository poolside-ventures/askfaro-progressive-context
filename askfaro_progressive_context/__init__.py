"""askfaro-progressive-context: compile any content into a tiered, budget-aware,
agent-navigable progressive-disclosure manifest, plus an expansion protocol."""

from .eval import CaseResult, EvalReport, NavCase, run_case, run_eval
from .llm import LLMClient, OpenAICompatibleClient
from .loader import (
    AsyncFetcher,
    AsyncManifestLoader,
    FetchOutcome,
    Fetcher,
    FileStore,
    Identity,
    LoaderError,
    ManifestKey,
    ManifestLoader,
    ManifestStore,
    MemoryStore,
    StoredManifest,
    identity_of,
)
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

__version__ = "0.3.0"

__all__ = [
    "AsyncFetcher",
    "AsyncManifestLoader",
    "BudgetExceeded",
    "CaseResult",
    "EvalReport",
    "FetchOutcome",
    "Fetcher",
    "FileStore",
    "FrontierEntry",
    "Identity",
    "KeywordNavigator",
    "LLMClient",
    "LLMNavigator",
    "LOCAL",
    "REMOTE",
    "LeafResolver",
    "LoaderError",
    "Manifest",
    "ManifestKey",
    "ManifestLoader",
    "ManifestStore",
    "MemoryStore",
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
    "StoredManifest",
    "VIEW_LEVELS",
    "Variant",
    "dict_resolver",
    "estimate_tokens",
    "identity_of",
    "make_tokenizer",
    "render_descriptor",
    "run_case",
    "run_eval",
    "schema_errors",
    "structural_errors",
    "validate",
]
