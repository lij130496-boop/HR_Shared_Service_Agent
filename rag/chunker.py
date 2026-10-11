from __future__ import annotations

from dataclasses import dataclass, asdict
from .document_loader import RawBlock


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    heading: str | None
    page: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def chunk_blocks(
    blocks: list[RawBlock],
    target_chars: int = 650,
    overlap_chars: int = 100,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    current_source = ""
    current_heading = None
    current_page = None
    seq = 1

    def flush():
        nonlocal buf, size, seq
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            chunks.append(
                Chunk(
                    id=f"chunk-{seq:04d}",
                    text=text,
                    source=current_source,
                    heading=current_heading,
                    page=current_page,
                )
            )
            seq += 1

        if overlap_chars > 0 and text:
            tail = text[-overlap_chars:]
            buf = [tail]
            size = len(tail)
        else:
            buf = []
            size = 0

    for block in blocks:
        # 文档、章节或PDF页切换时优先断开，来源更清晰
        boundary_changed = (
            buf
            and (
                block.source != current_source
                or block.heading != current_heading
                or (
                    block.page is not None
                    and current_page is not None
                    and block.page != current_page
                )
            )
        )
        if boundary_changed:
            flush()
            buf = []
            size = 0

        current_source = block.source
        current_heading = block.heading
        current_page = block.page

        if size + len(block.text) > target_chars and buf:
            flush()

        buf.append(block.text)
        size += len(block.text)

    flush()
    return chunks
