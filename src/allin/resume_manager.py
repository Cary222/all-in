"""Multi-resume manager for All In.

Supports uploading, storing, indexing, selecting, and deleting multiple resumes,
while keeping backward compatibility with the legacy single resume configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from allin.config import save_config
from allin.web.resume_info import (
    build_resume_info_payload,
    format_file_size,
    format_uploaded_at,
    is_default_resume_placeholder,
    read_and_repair_resume_text,
    resolve_resume_filesystem_path,
)
from allin.web.resume_names import select_resume_markdown_filename
from allin.web.resume_original import (
    companion_pdf_path,
    remove_companion_pdf,
    resolve_configured_resume_files,
    upload_keeps_original_pdf,
    write_resume_artifacts,
)
from allin.web.resume_text import sanitize_resume_text
from allin.web.resume_upload import (
    ResumeUploadError,
    prepare_resume_content,
    safe_resume_filename,
)

INDEX_FILENAME = "resumes.json"


@dataclass
class ResumeMetadata:
    id: str
    name: str
    target_direction: str
    filename: str
    path: str
    is_default: bool
    uploaded_at: str
    mtime: float
    size: int
    has_original_pdf: bool = False
    original_filename: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["size_label"] = format_file_size(self.size)
        return data


def get_resume_storage_dir(config: dict[str, Any] | None = None, base_dir: Path | None = None) -> Path:
    """Return the directory where resumes and their index are stored."""
    configured = (config or {}).get("profile", {}).get("resume_output_dir") or "./data/resumes"
    path = Path(configured)
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path.resolve()


def _get_index_path(storage_dir: Path) -> Path:
    return storage_dir / INDEX_FILENAME


def _load_index_data(storage_dir: Path) -> list[dict[str, Any]]:
    index_path = _get_index_path(storage_dir)
    if not index_path.is_file():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "resumes" in data:
            return list(data["resumes"])
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_index_data(storage_dir: Path, resumes: list[dict[str, Any]]) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    index_path = _get_index_path(storage_dir)
    payload = {"resumes": resumes, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sync_legacy_profile_resume(
    config: dict[str, Any],
    default_path: str,
    config_path: Path | None = None,
) -> None:
    """Keep config['profile']['resume_path'] pointing at the default resume."""
    if not config:
        return
    profile = config.setdefault("profile", {})
    if profile.get("resume_path") != default_path:
        profile["resume_path"] = default_path
        if config_path:
            save_config(config, config_path)


def list_resumes(
    config: dict[str, Any],
    base_dir: Path | None = None,
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List all registered resumes.
    
    If the index is empty but a valid legacy resume exists in config,
    it is automatically indexed as the default resume.
    """
    storage_dir = get_resume_storage_dir(config, base_dir)
    items = _load_index_data(storage_dir)
    
    # Filter out missing files
    valid_items: list[dict[str, Any]] = []
    has_default = False
    for item in items:
        p = Path(item.get("path", ""))
        if p.is_file():
            valid_items.append(item)
            if item.get("is_default"):
                has_default = True

    # If empty or none default, check legacy resume_path
    if not valid_items:
        legacy_path = config.get("profile", {}).get("resume_path", "")
        if legacy_path and not is_default_resume_placeholder(legacy_path):
            resolved = resolve_resume_filesystem_path(legacy_path, base_dir)
            md_path, pdf_path = resolve_configured_resume_files(resolved)
            target_file = md_path if md_path.is_file() else pdf_path
            if target_file.is_file():
                stat = target_file.stat()
                legacy_item = ResumeMetadata(
                    id="default",
                    name="默认简历",
                    target_direction="通用",
                    filename=target_file.name,
                    path=str(target_file.resolve()),
                    is_default=True,
                    uploaded_at=format_uploaded_at(stat.st_mtime),
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    has_original_pdf=pdf_path.is_file(),
                    original_filename=pdf_path.name if pdf_path.is_file() else None,
                ).to_dict()
                valid_items.append(legacy_item)
                _save_index_data(storage_dir, valid_items)
                has_default = True

    # Ensure at least one default if items exist
    if valid_items and not has_default:
        valid_items[0]["is_default"] = True
        _save_index_data(storage_dir, valid_items)
        _sync_legacy_profile_resume(config, valid_items[0]["path"], config_path)

    # Sort: default first, then newest
    valid_items.sort(key=lambda x: (not x.get("is_default", False), -x.get("mtime", 0)))
    return valid_items


def get_resume_by_id(
    resume_id: str | None,
    config: dict[str, Any],
    base_dir: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Retrieve resume metadata and content by id.
    
    If resume_id is None, empty, or 'default', loads the default resume.
    Returns (meta_dict, content_str).
    """
    resumes = list_resumes(config, base_dir)
    if not resumes:
        # Fallback to legacy path directly if present
        legacy_path = config.get("profile", {}).get("resume_path", "")
        if legacy_path:
            p = resolve_resume_filesystem_path(legacy_path, base_dir)
            if p.is_file():
                return None, read_and_repair_resume_text(p)
        return None, ""

    target_id = (resume_id or "").strip()
    selected: dict[str, Any] | None = None
    if not target_id or target_id == "default":
        # Find default
        for r in resumes:
            if r.get("is_default"):
                selected = r
                break
        if not selected and resumes:
            selected = resumes[0]
    else:
        for r in resumes:
            if r.get("id") == target_id:
                selected = r
                break
        if not selected:
            # Fallback to default
            for r in resumes:
                if r.get("is_default"):
                    selected = r
                    break
            if not selected and resumes:
                selected = resumes[0]

    if not selected:
        return None, ""

    file_path = Path(selected["path"])
    content = read_and_repair_resume_text(file_path) if file_path.is_file() else ""
    return selected, content


def get_resume_text(
    resume_id: str | None,
    config: dict[str, Any],
    base_dir: Path | None = None,
) -> str:
    """Get clean markdown text of the specified resume (or default)."""
    _, text = get_resume_by_id(resume_id, config, base_dir)
    return text


def save_resume_file(
    content: bytes,
    raw_filename: str,
    *,
    name: str = "",
    target_direction: str = "",
    is_default: bool = False,
    config: dict[str, Any],
    base_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Process uploaded resume file (md/docx/pdf), store in items/ folder and update index."""
    if len(content) > 10 * 1024 * 1024:
        raise ResumeUploadError("文件大小超过 10MB 限制")

    safe_name, stored_content = prepare_resume_content(raw_filename, content)
    resume_id = f"res_{uuid.uuid4().hex[:8]}"
    storage_dir = get_resume_storage_dir(config, base_dir)
    item_dir = storage_dir / "items" / resume_id
    item_dir.mkdir(parents=True, exist_ok=True)

    dest = item_dir / safe_name
    original_pdf_bytes = content if upload_keeps_original_pdf(raw_filename) else None
    write_resume_artifacts(dest, stored_content, original_pdf_bytes=original_pdf_bytes)

    display_name = (name or "").strip() or Path(safe_name).stem
    direction = (target_direction or "").strip() or "通用"
    stat = dest.stat()
    has_pdf = original_pdf_bytes is not None

    resumes = list_resumes(config, base_dir, config_path)
    if not resumes:
        is_default = True

    if is_default:
        for r in resumes:
            r["is_default"] = False

    new_meta = ResumeMetadata(
        id=resume_id,
        name=display_name,
        target_direction=direction,
        filename=safe_name,
        path=str(dest.resolve()),
        is_default=is_default,
        uploaded_at=format_uploaded_at(stat.st_mtime),
        mtime=stat.st_mtime,
        size=len(stored_content),
        has_original_pdf=has_pdf,
        original_filename=dest.with_suffix(".pdf").name if has_pdf else None,
    ).to_dict()

    resumes.append(new_meta)
    _save_index_data(storage_dir, resumes)

    if is_default:
        _sync_legacy_profile_resume(config, str(dest.resolve()), config_path)

    return new_meta


def update_resume_meta(
    resume_id: str,
    *,
    name: str | None = None,
    target_direction: str | None = None,
    is_default: bool | None = None,
    config: dict[str, Any],
    base_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Update metadata for an existing resume."""
    storage_dir = get_resume_storage_dir(config, base_dir)
    resumes = list_resumes(config, base_dir, config_path)
    target = None
    for r in resumes:
        if r.get("id") == resume_id:
            target = r
            break

    if not target:
        raise KeyError(f"未找到简历: {resume_id}")

    if name is not None and str(name).strip():
        target["name"] = str(name).strip()
    if target_direction is not None:
        target["target_direction"] = str(target_direction).strip()

    if is_default is True:
        for r in resumes:
            r["is_default"] = False
        target["is_default"] = True
        _sync_legacy_profile_resume(config, target["path"], config_path)

    _save_index_data(storage_dir, resumes)
    return target


def delete_resume_by_id(
    resume_id: str,
    config: dict[str, Any],
    base_dir: Path | None = None,
    config_path: Path | None = None,
) -> bool:
    """Delete a resume by its ID and clean up files."""
    storage_dir = get_resume_storage_dir(config, base_dir)
    resumes = list_resumes(config, base_dir, config_path)
    target = None
    remaining: list[dict[str, Any]] = []

    for r in resumes:
        if r.get("id") == resume_id:
            target = r
        else:
            remaining.append(r)

    if not target:
        return False

    # Clean up physical files
    try:
        target_path = Path(target.get("path", ""))
        if target_path.is_file():
            # If stored in item subfolder, remove entire subfolder
            if target_path.parent.name == resume_id and target_path.parent.parent.name == "items":
                shutil.rmtree(target_path.parent, ignore_errors=True)
            else:
                remove_companion_pdf(target_path)
                target_path.unlink(missing_ok=True)
    except Exception:
        pass

    # If deleted resume was default, assign default to first remaining
    if target.get("is_default") and remaining:
        remaining[0]["is_default"] = True
        _sync_legacy_profile_resume(config, remaining[0]["path"], config_path)
    elif not remaining:
        _sync_legacy_profile_resume(config, "", config_path)

    _save_index_data(storage_dir, remaining)
    return True
