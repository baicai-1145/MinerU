from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional

from mineru.utils.enum_class import BlockType

_KEYWORD_MAJOR = {
    "ABSTRACT",
    "ACKNOWLEDGMENT",
    "ACKNOWLEDGMENTS",
    "ACKNOWLEDGEMENT",
    "ACKNOWLEDGEMENTS",
    "CONCLUSION",
    "CONCLUSIONS",
    "DISCUSSION",
    "REFERENCES",
    "BIBLIOGRAPHY",
    "APPENDIX",
    "APPENDICES",
    "SUPPLEMENT",
    "SUPPLEMENTARY MATERIAL",
}

_KEYWORD_MINOR = {
    "INDEX TERMS",
    "KEYWORDS",
    "INDEX",
    "NOMENCLATURE",
    "SYMBOLS",
    "GLOSSARY",
}

_SECTION_PREFIXES = (
    "SECTION",
    "CHAPTER",
    "PART",
    "APPENDIX",
    "ANNEX",
    "ANNEXE",
    "SUPPLEMENT",
)

_PATTERN_PRIORITY = [
    "roman",
    "section_word",
    "arabic_depth_1",
    "appendix",
    "alpha",
    "arabic_depth_2",
    "arabic_depth_3",
    "keyword_major",
    "keyword_minor",
    "none",
]

_PATTERN_CHILDREN: dict[str, list[str]] = {
    "roman": ["alpha", "arabic_depth_2", "arabic_depth_3"],
    "section_word": ["alpha", "arabic_depth_2"],
    "arabic_depth_1": ["arabic_depth_2", "arabic_depth_3"],
    "appendix": ["alpha"],
    "alpha": ["arabic_depth_2"],
}

_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

_MIN_PATTERN_OCCURRENCES = 2
_DOC_TITLE_DISQUALIFIERS = _KEYWORD_MAJOR | _KEYWORD_MINOR


def annotate_title_levels(
    pdf_info_dict: Iterable[dict],
    merge_text_fn: Callable[[dict], str],
) -> None:
    candidates: list[dict] = []
    order = 0
    for page in pdf_info_dict:
        para_blocks = page.get("para_blocks") or []
        page_idx = page.get("page_idx", 0)
        for block in para_blocks:
            if block.get("type") != BlockType.TITLE:
                continue
            text = merge_text_fn(block).strip()
            normalized = _normalize_text(text)
            if not normalized:
                continue
            bbox = block.get("bbox") or []
            height = float(bbox[3] - bbox[1]) if len(bbox) >= 4 else 0.0
            pattern_key, meta = _classify_title_pattern(normalized)
            candidate = {
                "block": block,
                "text": normalized,
                "text_upper": normalized.upper(),
                "page_idx": page_idx,
                "order": order,
                "height": height,
                "pattern_key": pattern_key,
                "meta": meta,
            }
            candidates.append(candidate)
            order += 1

    if not candidates:
        return

    doc_title = _pick_document_title(candidates)
    if doc_title:
        doc_title["assigned_level"] = 1
        doc_title["block"]["_mineru_title_level"] = 1

    pattern_stats = _collect_pattern_stats(candidates)
    level_assignments = _determine_level_assignments(pattern_stats)

    for candidate in candidates:
        if candidate.get("assigned_level"):
            continue
        key = candidate["pattern_key"]
        level = level_assignments.get(key)
        if level is None:
            level = level_assignments.get("none", 2)
        level = max(1, min(int(level), 4))
        candidate["block"]["_mineru_title_level"] = level


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _classify_title_pattern(text: str) -> tuple[str, dict]:
    upper = text.upper()
    for prefix in _SECTION_PREFIXES:
        if upper.startswith(prefix + " "):
            remainder = upper[len(prefix):].strip()
            label_token = remainder.split(" ", 1)[0].strip(" .:)") if remainder else ""
            if prefix == "APPENDIX":
                return "appendix", {"prefix": prefix, "label": label_token}
            return "section_word", {"prefix": prefix, "label": label_token}

    if upper in _KEYWORD_MAJOR:
        return "keyword_major", {"keyword": upper}
    if upper in _KEYWORD_MINOR:
        return "keyword_minor", {"keyword": upper}

    numeric_token = _extract_numeric_token(text)
    primary_token = numeric_token or text.split(" ", 1)[0]
    cleaned = _clean_token(primary_token)
    if not cleaned:
        return "none", {}

    if _looks_like_roman(cleaned):
        value = _roman_to_int(cleaned)
        if value:
            return "roman", {"value": value}

    if _looks_like_arabic(cleaned):
        depth = cleaned.count(".") + 1
        if depth <= 1:
            return "arabic_depth_1", {"value": cleaned}
        if depth == 2:
            return "arabic_depth_2", {"value": cleaned}
        return "arabic_depth_3", {"value": cleaned}

    if len(cleaned) == 1 and cleaned.isalpha():
        return "alpha", {"value": cleaned.upper()}

    return "none", {}


def _extract_numeric_token(text: str) -> Optional[str]:
    candidate = text.lstrip("([")
    match = re.match(r"^(\d+(?:\s*[\.\-]\s*\d+)+)", candidate)
    if not match:
        return None
    token = match.group(1)
    token = token.replace("-", ".")
    token = re.sub(r"\s+", "", token)
    return token


def _clean_token(token: str) -> str:
    cleaned = token.strip()
    cleaned = cleaned.lstrip("([")
    cleaned = cleaned.rstrip(").,:;-")
    return cleaned


def _looks_like_roman(token: str) -> bool:
    if not token:
        return False
    return all(ch in _ROMAN_VALUES for ch in token.upper())


def _roman_to_int(token: str) -> Optional[int]:
    total = 0
    prev = 0
    for char in reversed(token.upper()):
        value = _ROMAN_VALUES.get(char)
        if not value:
            return None
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def _looks_like_arabic(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)*", token))


def _pick_document_title(candidates: List[dict]) -> Optional[dict]:
    best = None
    best_score = 0.0
    for candidate in candidates:
        if candidate["pattern_key"] != "none":
            continue
        if candidate["text_upper"] in _DOC_TITLE_DISQUALIFIERS:
            continue
        if candidate["page_idx"] > 1:
            continue
        score = (candidate["height"] or 0.0) * max(1, len(candidate["text"]))
        if score <= 0:
            score = len(candidate["text"])
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _collect_pattern_stats(candidates: List[dict]) -> Dict[str, List[dict]]:
    stats: Dict[str, List[dict]] = {}
    for candidate in candidates:
        if candidate.get("assigned_level"):
            continue
        key = candidate["pattern_key"]
        stats.setdefault(key, []).append(candidate)
    return stats


def _determine_level_assignments(pattern_stats: Dict[str, List[dict]]) -> Dict[str, int]:
    if not pattern_stats:
        return {}

    dominant = _select_dominant_pattern(pattern_stats)
    ordered_keys: list[str] = []
    if dominant:
        ordered_keys.append(dominant)
        for child in _PATTERN_CHILDREN.get(dominant, []):
            if child in pattern_stats and child not in ordered_keys:
                ordered_keys.append(child)

    for key in _PATTERN_PRIORITY:
        if key in pattern_stats and key not in ordered_keys:
            ordered_keys.append(key)

    level_assignments: dict[str, int] = {}
    current_level = 2
    for key in ordered_keys:
        if key in {"keyword_major", "keyword_minor"}:
            continue
        level_assignments[key] = current_level
        if current_level < 4:
            current_level += 1

    base_level = level_assignments.get(dominant, 2)
    if "keyword_major" in pattern_stats:
        level_assignments["keyword_major"] = base_level
    if "keyword_minor" in pattern_stats:
        level_assignments["keyword_minor"] = min(base_level + 1, 4)
    if "appendix" in pattern_stats and "appendix" not in level_assignments:
        level_assignments["appendix"] = base_level
    if "none" in pattern_stats and "none" not in level_assignments:
        level_assignments["none"] = base_level
    return level_assignments


def _select_dominant_pattern(pattern_stats: Dict[str, List[dict]]) -> Optional[str]:
    def _primary_keys() -> list[str]:
        return [
            key
            for key in _PATTERN_PRIORITY
            if key in pattern_stats and key not in {"keyword_major", "keyword_minor", "none"}
        ]

    eligible = [
        key
        for key in _primary_keys()
        if len(pattern_stats[key]) >= _MIN_PATTERN_OCCURRENCES
    ]
    if eligible:
        eligible.sort(key=lambda key: (-len(pattern_stats[key]), _pattern_priority_index(key)))
        return eligible[0]

    fallback = _primary_keys()
    if fallback:
        return fallback[0]
    return None


def _pattern_priority_index(key: str) -> int:
    try:
        return _PATTERN_PRIORITY.index(key)
    except ValueError:
        return len(_PATTERN_PRIORITY)
