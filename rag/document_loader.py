from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from docx import Document
from pypdf import PdfReader


@dataclass
class RawBlock:
    text: str
    source: str
    page: int | None = None
    heading: str | None = None


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split()).strip()


def load_docx(path: Path) -> list[RawBlock]:
    doc = Document(path)
    blocks: list[RawBlock] = []
    current_heading: str | None = None

    for p in doc.paragraphs:
        text = _clean(p.text)
        if not text:
            continue

        style_name = (p.style.name or "") if p.style else ""
        if style_name.lower().startswith("heading") or style_name.startswith("标题"):
            current_heading = text
            continue

        # 对很多中文制度文档，标题样式经常丢失，因此额外识别“第X章”
        if len(text) <= 40 and (text.startswith("第") and "章" in text[:12]):
            current_heading = text
            continue

        blocks.append(
            RawBlock(
                text=text,
                source=path.name,
                heading=current_heading,
            )
        )
    return blocks


def load_pdf(path: Path) -> list[RawBlock]:
    reader = PdfReader(str(path))
    blocks: list[RawBlock] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for paragraph in text.splitlines():
            paragraph = _clean(paragraph)
            if paragraph:
                blocks.append(
                    RawBlock(
                        text=paragraph,
                        source=path.name,
                        page=i,
                    )
                )
    return blocks


def load_txt(path: Path) -> list[RawBlock]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [
        RawBlock(text=_clean(line), source=path.name)
        for line in text.splitlines()
        if _clean(line)
    ]


def load_file(path: Path) -> list[RawBlock]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return load_docx(path)
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix in {".txt", ".md"}:
        return load_txt(path)
    raise ValueError(f"暂不支持的文件类型: {path.suffix}")


def iter_supported_files(folder: Path) -> Iterable[Path]:
    supported = {".docx", ".pdf", ".txt", ".md"}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in supported:
            yield path
