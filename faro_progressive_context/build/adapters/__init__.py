"""Adapters turn a source on disk into a SourceTree.

Phase 1 ships the four already-hierarchical kinds (no structure inference):
docs, skills, tools, memory.
"""

from .base import Adapter, get_adapter, register_adapter
from .docs import DocsAdapter
from .memory import MemoryAdapter
from .skills import SkillsAdapter
from .tools import ToolsAdapter

__all__ = [
    "Adapter",
    "DocsAdapter",
    "MemoryAdapter",
    "SkillsAdapter",
    "ToolsAdapter",
    "get_adapter",
    "register_adapter",
]
