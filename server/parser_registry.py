import os
import importlib
from pathlib import Path
from parsers.base import BaseParser

_registry: dict[str, BaseParser] = {}

def _discover_parsers():
    """Auto-discover parser classes in the parsers/ directory."""
    global _registry
    parsers_dir = Path(__file__).parent / 'parsers'
    for f in parsers_dir.iterdir():
        if f.name.startswith('_') or f.name == 'base.py' or not f.name.endswith('.py'):
            continue
        module_name = f'parsers.{f.stem}'
        try:
            mod = importlib.import_module(module_name)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BaseParser) and obj is not BaseParser:
                    instance = obj()
                    _registry[instance.name] = instance
        except Exception as e:
            print(f'[parser_registry] Failed to load {module_name}: {e}')

def get_parser_for_content(raw_content: str, file_ext: str) -> BaseParser | None:
    """Find a parser that can handle the given content."""
    if not _registry:
        _discover_parsers()
    for parser in _registry.values():
        if file_ext in parser.file_extensions and parser.detect(raw_content):
            return parser
    return None

def list_parsers() -> list[dict]:
    """List all registered parsers."""
    if not _registry:
        _discover_parsers()
    return [{'name': p.name, 'display_name': p.display_name, 'extensions': p.file_extensions} for p in _registry.values()]
