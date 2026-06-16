"""
server/workspace_manager.py — Workspace folder + staging area management.
"""
import os
import json
import uuid
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Staging: session-level temp directory
_staging_dir = Path(tempfile.gettempdir()) / 'baogu_staging'
_staging_dir.mkdir(parents=True, exist_ok=True)

# Workspace: user-configured persistent directory
_workspace_path: Optional[Path] = None

ALLOWED_EXTENSIONS = {'.json', '.jsonl', '.txt'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# ─── Workspace config ──────────────────────────────────────────
def get_workspace_path() -> Path:
    global _workspace_path
    if _workspace_path is None:
        # Default: project_root/data/
        _project_root = Path(__file__).resolve().parents[1]
        _workspace_path = _project_root / 'data'
        _workspace_path.mkdir(parents=True, exist_ok=True)
    _workspace_path.mkdir(parents=True, exist_ok=True)
    return _workspace_path

def set_workspace_path(path: str):
    global _workspace_path
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    _workspace_path = p

# ─── Staging ────────────────────────────────────────────────────
def import_to_staging(file_path: str, file_name: str, content: bytes) -> dict:
    """Save uploaded file to staging. Returns staging info dict."""
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {ext}。支持: {', '.join(ALLOWED_EXTENSIONS)}")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"文件过大: {len(content)} bytes (> {MAX_FILE_SIZE})")

    staging_id = f"{uuid.uuid4().hex[:8]}_{file_name}"
    dest = _staging_dir / staging_id
    dest.write_bytes(content)

    return {
        'id': staging_id,
        'name': file_name,
        'size': len(content),
        'imported_at': datetime.now(timezone.utc).isoformat(),
    }

def list_staging() -> list[dict]:
    """List all files in staging."""
    results = []
    for f in _staging_dir.iterdir():
        if f.is_file():
            stat = f.stat()
            results.append({
                'id': f.name,
                'name': '_'.join(f.name.split('_')[1:]),  # strip uuid prefix
                'size': stat.st_size,
                'imported_at': datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            })
    return sorted(results, key=lambda x: x['imported_at'], reverse=True)

def get_staging_file(staging_id: str) -> Path | None:
    """Get staging file path. Returns None if not found."""
    p = _staging_dir / staging_id
    return p if p.exists() else None

def delete_staging_file(staging_id: str) -> bool:
    """Delete a staging file. Returns True if deleted."""
    p = _staging_dir / staging_id
    if not p.exists():
        return False
    p.unlink()
    return True

# ─── Persisted (workspace) ──────────────────────────────────────
def list_persisted() -> list[dict]:
    """List all files in the workspace."""
    ws = get_workspace_path()
    results = []
    for f in ws.iterdir():
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            stat = f.stat()
            results.append({
                'name': f.name,
                'path': str(f),
                'size': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return sorted(results, key=lambda x: x['modified_at'], reverse=True)

def persist_file(staging_id: str) -> dict:
    """Copy staging file to workspace. Returns persisted file info."""
    src = get_staging_file(staging_id)
    if src is None:
        raise FileNotFoundError(f"Staging file not found: {staging_id}")

    ws = get_workspace_path()
    # Extract original filename (after uuid_ prefix)
    dest_name = '_'.join(staging_id.split('_')[1:])
    dest = ws / dest_name

    # If exists, add suffix
    if dest.exists():
        base, ext = os.path.splitext(dest_name)
        dest = ws / f"{base}_{uuid.uuid4().hex[:4]}{ext}"

    shutil.copy2(src, dest)

    stat = dest.stat()
    return {
        'name': dest.name,
        'path': str(dest),
        'size': stat.st_size,
        'modified_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

def browse_workspace(subdir: str = "") -> list[dict]:
    """List parseable files in the workspace (optionally in a subdirectory).

    Returns list of {name, path, size, modified_at}.
    """
    ws = get_workspace_path()
    target = (ws / subdir).resolve() if subdir else ws
    # Security: ensure target is within workspace
    if not str(target).startswith(str(ws)):
        raise ValueError(f"Path outside workspace: {target}")
    if not target.exists():
        return []

    results = []
    for f in sorted(target.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            stat = f.stat()
            results.append({
                'name': f.name,
                'path': str(f),
                'size': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return results


def cleanup_staging():
    """Remove all staging files. Called on server shutdown."""
    for f in _staging_dir.iterdir():
        if f.is_file():
            f.unlink()
