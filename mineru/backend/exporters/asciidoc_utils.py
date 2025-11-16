from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional

from mineru.utils.enum_class import BlockType, ContentType

_COLUMN_CENTER_BOUNDARY = 500
_MIN_BLOCKS_FOR_COLUMN_CHECK = 6

_TEXTUAL_BLOCK_TYPES = {
    BlockType.TEXT,
    BlockType.LIST,
    BlockType.INDEX,
    BlockType.TITLE,
}

for optional in [
    getattr(BlockType, "REF_TEXT", None),
    getattr(BlockType, "PHONETIC", None),
    getattr(BlockType, "HEADER", None),
    getattr(BlockType, "FOOTER", None),
    getattr(BlockType, "PAGE_NUMBER", None),
    getattr(BlockType, "ASIDE_TEXT", None),
    getattr(BlockType, "PAGE_FOOTNOTE", None),
]:
    if optional:
        _TEXTUAL_BLOCK_TYPES.add(optional)


def markdown_to_asciidoc_block(text: str) -> str:
    lines = text.splitlines()
    converted: list[str] = []
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            converted.append(f"{'=' * level} {heading.group(2)}")
        else:
            converted.append(line)

    body = "\n".join(converted)

    def _img(match: re.Match[str]) -> str:
        alt = (match.group("alt") or "").strip()
        path = match.group("path")
        alt_part = alt if alt else ""
        return f"image::{path}[{alt_part}]"

    return re.sub(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)", _img, body)


def detect_page_column_count(para_blocks: Iterable[dict]) -> int:
    bboxes: list[list[int]] = []
    for block in para_blocks:
        if block.get("type") not in _TEXTUAL_BLOCK_TYPES:
            continue
        bbox = block.get("bbox")
        if not bbox or bbox[2] <= bbox[0]:
            continue
        bboxes.append(bbox)

    if len(bboxes) < _MIN_BLOCKS_FOR_COLUMN_CHECK:
        return 1

    centers = [(bbox[0] + bbox[2]) / 2 for bbox in bboxes]
    widths = [bbox[2] - bbox[0] for bbox in bboxes]
    left = sum(1 for c in centers if c < _COLUMN_CENTER_BOUNDARY)
    right = len(centers) - left
    if min(left, right) < len(centers) * 0.25:
        return 1

    narrow_ratio = sum(1 for w in widths if w < 520) / len(widths)
    if narrow_ratio < 0.55:
        return 1

    left_center = sum(c for c in centers if c < _COLUMN_CENTER_BOUNDARY) / max(left, 1)
    right_center = sum(c for c in centers if c >= _COLUMN_CENTER_BOUNDARY) / max(right, 1)
    if right_center - left_center < 200:
        return 1
    return 2


def detect_document_dual_column(pdf_info_dict: Iterable[dict]) -> bool:
    columns: list[int] = []
    for page in pdf_info_dict:
        para_blocks = page.get("para_blocks") or []
        if not para_blocks:
            continue
        columns.append(detect_page_column_count(para_blocks))

    if not columns:
        return False
    dual_ratio = sum(1 for c in columns if c == 2) / len(columns)
    return dual_ratio >= 0.5


def build_image_block(
    para_block: dict,
    page_size: Optional[List[int]],
    img_buket_path: str,
    merge_text_fn: Callable[[dict], str],
) -> Optional[str]:
    img_path = ""
    captions: list[str] = []
    footnotes: list[str] = []

    for block in para_block.get("blocks", []):
        block_type = block["type"]
        if block_type == BlockType.IMAGE_BODY:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["type"] == ContentType.IMAGE and span.get("image_path"):
                        img_path = f"{img_buket_path}/{span['image_path']}"
        elif block_type == BlockType.IMAGE_CAPTION:
            captions.append(merge_text_fn(block))
        elif block_type == BlockType.IMAGE_FOOTNOTE:
            footnotes.append(merge_text_fn(block))

    if not img_path:
        return None

    width_percent = 100
    bbox = para_block.get("bbox")
    if bbox:
        width_ratio = max(0.05, (bbox[2] - bbox[0]) / 1000.0)
        width_percent = max(25, min(100, int(round(width_ratio * 100))))

    attrs = [f"width={width_percent}%"]
    lines: list[str] = []
    if captions:
        lines.append(f".{' '.join(captions)}")
    lines.append(f"image::{img_path}[{', '.join(attrs)}]")
    if footnotes:
        lines.append(" ".join(footnotes))
    return "\n".join(lines)
