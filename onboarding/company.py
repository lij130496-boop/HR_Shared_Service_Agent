from __future__ import annotations

import json
from pathlib import Path


SUPPORTED_MAP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def find_company_map(assets_dir: Path) -> Path | None:
    if not assets_dir.exists():
        return None
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = assets_dir / f"company_map{suffix}"
        if candidate.exists():
            return candidate
    return None


def save_company_map(assets_dir: Path, filename: str, content: bytes) -> Path:
    assets_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_MAP_EXTENSIONS:
        raise ValueError("办公地图仅支持 PNG/JPG/JPEG/WEBP 图片。")

    for old in assets_dir.glob("company_map.*"):
        if old.is_file() and old.suffix.lower() in SUPPORTED_MAP_EXTENSIONS:
            old.unlink(missing_ok=True)

    target = assets_dir / f"company_map{suffix}"
    target.write_bytes(content)
    return target


def load_company_locations(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows: list[dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            if name:
                rows.append({"name": name, "description": description})
    return rows


def save_company_locations(path: Path, locations: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": str(item.get("name", "")).strip(),
            "description": str(item.get("description", "")).strip(),
        }
        for item in locations
        if str(item.get("name", "")).strip()
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_locations_text(text: str) -> list[dict[str, str]]:
    """每行格式：位置名称|说明。没有 | 时整行作为位置名称。"""
    rows: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            name, description = line.split("|", 1)
        else:
            name, description = line, ""
        name = name.strip()
        description = description.strip()
        if name:
            rows.append({"name": name, "description": description})
    return rows


def locations_to_text(locations: list[dict[str, str]]) -> str:
    lines = []
    for item in locations:
        name = str(item.get("name", "")).strip()
        description = str(item.get("description", "")).strip()
        if not name:
            continue
        lines.append(f"{name}|{description}" if description else name)
    return "\n".join(lines)
