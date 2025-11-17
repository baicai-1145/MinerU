from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional

from mineru.utils.enum_class import BlockType, ContentType

_MIN_BLOCKS_FOR_COLUMN_CHECK = 6
_CENTER_TOLERANCE = 0.03  # relative to page width
_COLUMN_MARGIN_RATIO = 0.1
_NARROW_WIDTH_RATIO = 0.42
_SPAN_FULL_THRESHOLD = 0.68

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


def detect_page_column_count(para_blocks: Iterable[dict], page_size: Optional[List[float]]) -> dict:
    bboxes: list[list[int]] = []
    for block in para_blocks:
        if block.get("type") not in _TEXTUAL_BLOCK_TYPES:
            continue
        bbox = block.get("bbox")
        if not bbox or bbox[2] <= bbox[0]:
            continue
        bboxes.append(bbox)

    if len(bboxes) < _MIN_BLOCKS_FOR_COLUMN_CHECK:
        return {"is_dual": False}

    page_width = page_size[0] if page_size and page_size[0] else 1000.0
    centers = [(bbox[0] + bbox[2]) / 2 for bbox in bboxes]
    widths = [bbox[2] - bbox[0] for bbox in bboxes]
    boundary = page_width * 0.5
    left = sum(1 for c in centers if c < boundary)
    right = len(centers) - left
    if min(left, right) < len(centers) * 0.2:
        return {"is_dual": False}

    narrow_ratio = sum(1 for w in widths if w < page_width * _NARROW_WIDTH_RATIO) / len(widths)
    if narrow_ratio < 0.4:
        return {"is_dual": False}

    left_center = sum(c for c in centers if c < boundary) / max(left, 1)
    right_center = sum(c for c in centers if c >= boundary) / max(right, 1)
    if right_center - left_center < page_width * 0.2:
        return {"is_dual": False}
    return {
        "is_dual": True,
        "left_center": left_center / page_width,
        "right_center": right_center / page_width,
        "column_width_ratio": sum(widths)/(len(widths)*page_width),
    }


def detect_document_dual_column(pdf_info_dict: Iterable[dict]) -> tuple[bool, set[int]]:
    has_dual = False
    dual_pages: set[int] = set()
    for page in pdf_info_dict:
        para_blocks = page.get("para_blocks") or []
        if not para_blocks:
            continue
        analysis = detect_page_column_count(para_blocks, page.get("page_size"))
        page["_mineru_column_layout"] = analysis
        if analysis.get("is_dual"):
            has_dual = True
            dual_pages.add(page.get("page_idx", len(dual_pages)))
    return has_dual, dual_pages


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
    page_width = page_size[0] if page_size and page_size[0] else 1000.0
    if bbox:
        width_ratio = max(0.05, (bbox[2] - bbox[0]) / page_width)
        width_percent = max(25, min(100, int(round(width_ratio * 100))))

    attrs = [f"width={width_percent}%"]
    lines: list[str] = []
    # 先输出图片主体，再输出 caption/footnote，便于渲染器正确关联
    if captions:
        lines.append(f".{ ' '.join(captions) }")
    lines.append(f"image::{img_path}[{', '.join(attrs)}]")
    if footnotes:
        lines.append(" ".join(footnotes))
    return "\n".join(lines)


def get_block_layout_flags(
    bbox: Optional[List[float]],
    page_size: Optional[List[float]],
    page_layout: Optional[dict],
    block_type: Optional[str],
    text_level: Optional[int] = None,
) -> dict:
    flags = {
        "span_full": False,
        "center_page": False,
        "center_dual": False,
        "center_column": False,
    }
    if not bbox or not page_size or not page_size[0]:
        return flags
    page_width = page_size[0]
    block_width = bbox[2] - bbox[0]
    width_ratio = block_width / page_width
    center_ratio = (bbox[0] + bbox[2]) / (2 * page_width)

    is_dual_page = bool(page_layout and page_layout.get("is_dual"))

    if width_ratio >= _SPAN_FULL_THRESHOLD:
        flags["span_full"] = True
        # 跨列块默认也居中对齐
        flags["center_page"] = True
        return flags

    if not is_dual_page:
        if abs(center_ratio - 0.5) <= _CENTER_TOLERANCE:
            flags["center_page"] = True
        return flags

    left_center = page_layout.get("left_center", 0.25) if page_layout else 0.25
    right_center = page_layout.get("right_center", 0.75) if page_layout else 0.75
    left_dist = abs(center_ratio - left_center)
    right_dist = abs(center_ratio - right_center)
    is_column_block = width_ratio <= _NARROW_WIDTH_RATIO and min(left_dist, right_dist) <= _COLUMN_MARGIN_RATIO

    if is_column_block and block_type == BlockType.TITLE:
        flags["center_column"] = True
        return flags

    if is_column_block and block_type == BlockType.INTERLINE_EQUATION:
        # 列内公式，列内居中
        flags["center_column"] = True
        return flags

    if not is_column_block and abs(center_ratio - 0.5) <= _COLUMN_MARGIN_RATIO:
        flags["center_dual"] = True
    elif not is_column_block:
        flags["span_full"] = True

    return flags


def build_style_block(enable_two_column: bool) -> List[str]:
    css_lines = [
        ".text-center { text-align: center; }",
        ".mineru-paragraph { break-inside: avoid; }",
        ".mineru-span-full { column-span: all; display: block; }",
        ".mineru-paragraph.text-center .imageblock .title { text-align: center; }",
        ".mineru-span-full .imageblock .title { text-align: center; }",
        ".mineru-paragraph.text-center .imageblock { text-align: center; }",
        ".mineru-span-full .imageblock { text-align: center; }",
        ".mineru-paragraph.text-center .tableblock .title { text-align: center; }",
        ".mineru-span-full .tableblock .title { text-align: center; }",
    ]
    if enable_two_column:
        css_lines.append("body.mineru-two-column { column-count: 2; column-gap: 2.4em; }")
        css_lines.append("body.mineru-two-column p, body.mineru-two-column table, body.mineru-two-column img { break-inside: avoid; }")

    block: List[str] = ["++++", "<style>"]
    block.extend(css_lines)
    block.append("</style>")
    if enable_two_column:
        block.append(
            "<script>\n"
            "document.addEventListener('DOMContentLoaded', function() {\n"
            "  if (!document.body) return;\n"
            "  document.body.classList.add('mineru-two-column');\n"
            "});\n"
            "</script>"
        )
    block.append("++++")
    block.append("")
    return block
