"""
server/conversation_manager.py — Conversation CRUD backed by JSON files.
Each conversation is a .json file stored in a configurable directory.
Companion .results.json files store entrance control info per message index.
"""
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_CONV_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / '..' / 'data' / 'conversations'

conv_dir = _DEFAULT_CONV_DIR.resolve()


def set_conv_dir(path: str):
    global conv_dir
    conv_dir = Path(path).resolve()
    conv_dir.mkdir(parents=True, exist_ok=True)


def get_conv_dir() -> Path:
    conv_dir.mkdir(parents=True, exist_ok=True)
    return conv_dir


def _filepath(conv_id: str) -> Path:
    return get_conv_dir() / f'{conv_id}.json'


def _results_filepath(conv_id: str) -> Path:
    return get_conv_dir() / f'{conv_id}.results.json'


def list_conversations() -> list[dict]:
    """Return list of conversation summaries sorted by updated_at desc."""
    get_conv_dir().mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(get_conv_dir().glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        if '.results.' in f.name:
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            results.append({
                'id': data['id'],
                'title': data.get('title', '未命名对话'),
                'msg_count': len(data.get('messages', [])),
                'updated_at': data.get('updated_at', ''),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def create_conversation(messages: Optional[list[dict]] = None, meta: Optional[dict] = None) -> dict:
    """Create a new conversation file, return {id, created_at}."""
    conv_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        'version': 1,
        'id': conv_id,
        'title': '新建对话',
        'created_at': now,
        'updated_at': now,
        'meta': meta or {},
        'messages': messages or [],
    }
    _filepath(conv_id).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'id': conv_id, 'created_at': now}


def get_conversation(conv_id: str) -> dict | None:
    """Get full conversation by id, including results from companion file."""
    fp = _filepath(conv_id)
    if not fp.exists():
        return None
    data = json.loads(fp.read_text(encoding='utf-8'))

    # Load companion results file if it exists
    rfp = _results_filepath(conv_id)
    if rfp.exists():
        try:
            results_data = json.loads(rfp.read_text(encoding='utf-8'))
            data['results'] = results_data.get('results', {})
        except json.JSONDecodeError:
            data['results'] = {}
    else:
        data['results'] = {}

    return data


def save_conversation(conv_id: str, messages: list[dict], meta: Optional[dict] = None, results: Optional[dict] = None) -> bool:
    """Overwrite messages + meta. Also writes companion .results.json if provided."""
    fp = _filepath(conv_id)
    if not fp.exists():
        return False
    data = json.loads(fp.read_text(encoding='utf-8'))
    data['messages'] = messages
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    if meta:
        data['meta'] = {**data.get('meta', {}), **meta}
    # Auto-title from first user message
    for m in messages:
        if m.get('role') == 'user':
            data['title'] = m['content'][:40] + ('...' if len(m['content']) > 40 else '')
            break
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # Write companion results file
    if results is not None:
        rfp = _results_filepath(conv_id)
        rfp.write_text(json.dumps({'version': 1, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')

    return True


def delete_conversation(conv_id: str) -> bool:
    """Delete a conversation file and its companion results file."""
    fp = _filepath(conv_id)
    if not fp.exists():
        return False
    fp.unlink()
    # Also delete companion if exists
    rfp = _results_filepath(conv_id)
    if rfp.exists():
        rfp.unlink()
    return True
