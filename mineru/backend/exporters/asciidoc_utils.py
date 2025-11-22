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
    BlockType.INTERLINE_EQUATION,
    BlockType.CODE,
    BlockType.CODE_BODY,
    BlockType.CODE_CAPTION,
    BlockType.ALGORITHM,
    BlockType.REF_TEXT,
    BlockType.PHONETIC,
    BlockType.ASIDE_TEXT,
    BlockType.PAGE_FOOTNOTE,
}
_BODY_TEXT_BLOCK_TYPES = {
    BlockType.TEXT,
    BlockType.LIST,
    BlockType.INDEX,
    BlockType.REF_TEXT,
    BlockType.ASIDE_TEXT,
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


def _convert_html_table_to_asciidoc(text: str) -> Optional[str]:
    if "<table" not in text.lower():
        return None
    match = re.search(r"<table[^>]*>(.*?)</table>", text, flags=re.S | re.I)
    if not match:
        return None
    inner = match.group(1)
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, flags=re.S | re.I)
    if not rows_html:
        return None

    rows: list[list[str]] = []
    for row_html in rows_html:
        cells_html = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
        if not cells_html:
            continue
        cleaned_row: list[str] = []
        for cell in cells_html:
            cell_text = re.sub(r"<.*?>", "", cell)
            cell_text = re.sub(r"\s+", " ", cell_text)
            cell_text = cell_text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            cleaned_row.append(cell_text.strip())
        if cleaned_row:
            rows.append(cleaned_row)

    if not rows:
        return None

    max_cols = max(len(r) for r in rows)
    lines: list[str] = ['[options="header"]', "|==="]
    for r in rows:
        padded = r + [""] * (max_cols - len(r))
        lines.append("| " + " | ".join(padded))
    lines.append("|===")
    return "\n".join(lines)


def _convert_math_to_stem(text: str) -> str:
    def _repl_display(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        return "[stem]\n++++\n" + content + "\n++++"

    text = re.sub(r"\$\$\s*(.+?)\s*\$\$", _repl_display, text, flags=re.S)

    def _repl_inline(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        return f"stem:[{content}]"

    text = re.sub(r"\$(?!\$)(.+?)(?<!\$)\$", _repl_inline, text)
    return text


def markdown_to_asciidoc_block(text: str) -> str:
    table_adoc = _convert_html_table_to_asciidoc(text)
    if table_adoc:
        return table_adoc

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

    body = re.sub(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)", _img, body)
    body = _convert_math_to_stem(body)
    return body


def _get_effective_bbox(block: Optional[dict]) -> Optional[List[float]]:
    if not block:
        return None
    lines = block.get("lines")
    if lines:
        last_line = lines[-1] or {}
        spans = last_line.get("spans")
        if spans:
            last_span = spans[-1] or {}
            span_bbox = last_span.get("bbox")
            if span_bbox and span_bbox[2] > span_bbox[0]:
                return span_bbox
    bbox = block.get("bbox")
    if bbox and bbox[2] > bbox[0]:
        return bbox
    return None


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
    centers: list[float] = []
    widths: list[float] = []
    boundary = page_width * 0.5
    left_boxes: list[list[int]] = []
    right_boxes: list[list[int]] = []
    for bbox in bboxes:
        center = (bbox[0] + bbox[2]) / 2
        centers.append(center)
        width = bbox[2] - bbox[0]
        widths.append(width)
        if center < boundary:
            left_boxes.append(bbox)
        else:
            right_boxes.append(bbox)

    left = len(left_boxes)
    right = len(right_boxes)
    if min(left, right) < len(centers) * 0.2:
        return {"is_dual": False}

    narrow_ratio = sum(1 for w in widths if w < page_width * _NARROW_WIDTH_RATIO) / len(widths)
    if narrow_ratio < 0.4:
        return {"is_dual": False}

    def _median_center(column_boxes: list[list[int]]) -> float:
        if not column_boxes:
            return page_width * 0.25
        narrow_boxes = [box for box in column_boxes if (box[2] - box[0]) <= page_width * _NARROW_WIDTH_RATIO]
        boxes = narrow_boxes if narrow_boxes else column_boxes
        centers = sorted((box[0] + box[2]) / 2 for box in boxes)
        return centers[len(centers) // 2]

    left_center = _median_center(left_boxes)
    right_center = _median_center(right_boxes)
    if right_center - left_center < page_width * 0.2:
        return {"is_dual": False}

    def _column_width(column_boxes: list[list[int]]) -> float:
        if not column_boxes:
            return 0.0
        return sum((box[2] - box[0]) for box in column_boxes) / len(column_boxes)

    def _column_bounds(center_value: float, avg_width: float) -> Optional[list[float]]:
        if not avg_width:
            return None
        half_width = avg_width / 2
        left_edge = max(0.0, (center_value - half_width) / page_width)
        right_edge = min(1.0, (center_value + half_width) / page_width)
        if right_edge - left_edge <= 0:
            return None
        return [left_edge, right_edge]

    left_avg_width = _column_width(left_boxes)
    right_avg_width = _column_width(right_boxes)

    return {
        "is_dual": True,
        "left_center": left_center / page_width,
        "right_center": right_center / page_width,
        "column_width_ratio": sum(widths) / (len(widths) * page_width),
        "left_bounds": _column_bounds(left_center, left_avg_width),
        "right_bounds": _column_bounds(right_center, right_avg_width),
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

    body = "\n".join(lines)
    body = _convert_math_to_stem(body)
    return body


def get_block_layout_flags(
    bbox: Optional[List[float]],
    page_size: Optional[List[float]],
    page_layout: Optional[dict],
    block_type: Optional[str],
    text_level: Optional[int] = None,
    para_block: Optional[dict] = None,
    prev_block: Optional[dict] = None,
    next_block: Optional[dict] = None,
) -> dict:
    flags = {
        "span_full": False,
        "center_page": False,
        "center_dual": False,
        "center_column": False,
    }
    target_bbox = _get_effective_bbox(para_block) or bbox
    if not target_bbox or not page_size or not page_size[0]:
        return flags
    page_width = page_size[0]
    block_width = target_bbox[2] - target_bbox[0]
    width_ratio = block_width / page_width
    center_ratio = (target_bbox[0] + target_bbox[2]) / (2 * page_width)

    is_dual_page = bool(page_layout and page_layout.get("is_dual"))

    span_full_candidate = width_ratio >= _SPAN_FULL_THRESHOLD
    if span_full_candidate:
        flags["span_full"] = True

    def _is_gap_balanced(left_gap: float, right_gap: float, tolerance: float) -> bool:
        return abs(left_gap - right_gap) <= tolerance

    page_left = 0.0
    page_right = page_width
    page_tolerance = page_width * _CENTER_TOLERANCE

    def _cancel_center_due_to_neighbors() -> None:
        if block_type not in _BODY_TEXT_BLOCK_TYPES:
            return
        if not (flags["center_page"] or flags["center_dual"] or flags["center_column"]):
            return

        def _neighbor_indicates_body(neighbor: Optional[dict]) -> bool:
            if not neighbor or neighbor.get("type") not in _TEXTUAL_BLOCK_TYPES:
                return False
            neighbor_bbox = _get_effective_bbox(neighbor)
            if not neighbor_bbox:
                return False
            horizontal_gap = abs(neighbor_bbox[0] - target_bbox[0])
            if horizontal_gap > page_width * 0.06:
                return False
            left_gap_n = neighbor_bbox[0] - page_left
            right_gap_n = page_right - neighbor_bbox[2]
            return not _is_gap_balanced(
                left_gap_n,
                right_gap_n,
                max(page_tolerance, page_width * _COLUMN_MARGIN_RATIO),
            )

        if _neighbor_indicates_body(prev_block) or _neighbor_indicates_body(next_block):
            flags["center_page"] = False
            flags["center_dual"] = False
            flags["center_column"] = False

    if not is_dual_page:
        left_gap = target_bbox[0] - page_left
        right_gap = page_right - target_bbox[2]
        if _is_gap_balanced(left_gap, right_gap, page_tolerance):
            flags["center_page"] = True
        if not flags["center_page"] and span_full_candidate:
            flags["span_full"] = True
        _cancel_center_due_to_neighbors()
        return flags

    def _bounds_from_ratio(bounds: Optional[list[float]]) -> Optional[tuple[float, float]]:
        if not bounds or len(bounds) < 2:
            return None
        return bounds[0] * page_width, bounds[1] * page_width

    def _check_column(bounds: Optional[tuple[float, float]]) -> tuple[bool, bool]:
        if not bounds:
            return (False, False)
        col_left, col_right = bounds
        col_width = col_right - col_left
        membership_tol = max(page_width * _COLUMN_MARGIN_RATIO, col_width * 0.15)
        if target_bbox[0] < col_left - membership_tol or target_bbox[2] > col_right + membership_tol:
            return (False, False)
        symmetry_tol = max(page_tolerance, col_width * _CENTER_TOLERANCE)
        left_gap = target_bbox[0] - col_left
        right_gap = col_right - target_bbox[2]
        return True, _is_gap_balanced(left_gap, right_gap, symmetry_tol)

    raw_left_bounds = page_layout.get("left_bounds") if page_layout else None
    raw_right_bounds = page_layout.get("right_bounds") if page_layout else None
    left_bounds = _bounds_from_ratio(raw_left_bounds)
    right_bounds = _bounds_from_ratio(raw_right_bounds)
    in_left, left_centered = _check_column(left_bounds)
    in_right, right_centered = _check_column(right_bounds)
    if in_left or in_right:
        if left_centered or right_centered:
            flags["center_column"] = True
            _cancel_center_due_to_neighbors()
        return flags

    left_center = page_layout.get("left_center", 0.25) if page_layout else 0.25
    right_center = page_layout.get("right_center", 0.75) if page_layout else 0.75
    left_dist = abs(center_ratio - left_center)
    right_dist = abs(center_ratio - right_center)
    is_column_block = width_ratio <= _NARROW_WIDTH_RATIO and min(left_dist, right_dist) <= _COLUMN_MARGIN_RATIO

    if is_column_block:
        _cancel_center_due_to_neighbors()
        return flags

    left_gap = target_bbox[0] - page_left
    right_gap = page_right - target_bbox[2]
    if _is_gap_balanced(left_gap, right_gap, max(page_tolerance, page_width * _COLUMN_MARGIN_RATIO)):
        flags["center_dual"] = True
    elif span_full_candidate:
        flags["span_full"] = True

    _cancel_center_due_to_neighbors()

    return flags


def build_style_block(enable_two_column: bool) -> List[str]:
    css_lines = [
        ".text-center { text-align: center; }",
        ".mineru-paragraph { break-inside: avoid; text-align: left; }",
        ".mineru-paragraph.text-center { text-align: center; }",
        ".mineru-span-full { column-span: all; display: block; }",
        ".imageblock.text-center > .title { text-align: center; }",
        ".imageblock.mineru-paragraph.text-center > .title { text-align: center; }",
        ".imageblock.mineru-span-full > .title { text-align: center; }",
        ".imageblock.text-center { text-align: center; }",
        ".imageblock.mineru-span-full { text-align: center; }",
        ".tableblock.text-center > .title { text-align: center; }",
        ".tableblock.mineru-paragraph.text-center > .title { text-align: center; }",
        ".tableblock.mineru-span-full > .title { text-align: center; }",
        ".tableblock.text-center { margin-left: auto; margin-right: auto; }",
        ".tableblock.mineru-span-full { margin-left: auto; margin-right: auto; }",
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
    block.append(":stem: latexmath")
    block.append("")
    return block
