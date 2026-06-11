"""
L3_applier.py — 将 L3 微调申请写入 Intent.enriched
=================================================

L3 操作只修改 Intent.enriched 字典, 不修改树的结�?.
操作:
  modify_keywords     → enriched["keywords"]
  add_negative_examples → enriched["negative_examples"]
  add_attention       → enriched["attention"]

用法:
    from L3_applier import apply, apply_all
    apply(tree, application)
"""

try:
    from .grammar_tree import Prompt, IntentCatalog
    from .L2_enrich_application import EnrichApplication
except ImportError:
    from grammar_tree import Prompt, IntentCatalog
    from L2_enrich_application import EnrichApplication


def _find_intent_by_id(tree: Prompt, display_id: str):
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return None
    for group in catalog.groups:
        for intent in group.intents:
            if intent.display_id == display_id:
                return intent
    # fallback: search by "intents[X.Y]" pattern in target
    import re
    m = re.search(r"intents?\[(\d+\.\d+)\]", display_id)
    if m:
        did = m.group(1)
        for group in catalog.groups:
            for intent in group.intents:
                if intent.display_id == did:
                    return intent
    return None


def _apply_keywords(intent, app: EnrichApplication):
    action = app.content.get("action", "add")
    keywords = app.content.get("keywords", [])
    if not keywords:
        return

    current = intent.enriched.setdefault("keywords", [])
    if action == "add":
        for kw in keywords:
            if kw not in current:
                current.append(kw)
    elif action == "remove":
        for kw in keywords:
            if kw in current:
                current.remove(kw)


def _apply_negative(intent, app: EnrichApplication):
    examples = app.content.get("examples", [])
    if not examples:
        return

    current = intent.enriched.setdefault("negative_examples", [])
    for ex in examples:
        if ex not in current:
            current.append(ex)


def _apply_attention(intent, app: EnrichApplication):
    rules = app.content.get("rules", [])
    if not rules:
        return

    current = intent.enriched.setdefault("attention", [])
    for rule in rules:
        if rule not in current:
            current.append(rule)


_APPLIERS = {
    "modify_keywords": _apply_keywords,
    "add_negative_examples": _apply_negative,
    "add_attention": _apply_attention,
}


def apply(tree: Prompt, app: EnrichApplication) -> Prompt:
    """将单条 L3 申请写入 Intent.enriched (原地修改)."""
    applier = _APPLIERS.get(app.operation)
    if applier is None:
        raise ValueError(f"unknown L3 operation: {app.operation}")

    # target can be display_id like "2.2" or "intent_catalog.intents[2.2]"
    intent = _find_intent_by_id(tree, app.target)
    if intent is None:
        raise ValueError(f"intent not found for target: {app.target}")

    applier(intent, app)
    return tree


def apply_all(tree: Prompt, applications: list[EnrichApplication]) -> Prompt:
    for app in applications:
        apply(tree, app)
    return tree
