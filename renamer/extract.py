import re

from .models import DocumentRef
from .text_utils import format_filename_word, normalize_text, split_filename_words, tokenize

DOCUMENT_REF_RE = re.compile(r"\(Dokument Nr\.\s*\d{4,5}\s*[a-z]?\)", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
EU_CASE_RE = re.compile(r"\b(?:Rs\.?\s*)?[A-Z][-\u2010-\u2015]\s*\d{1,4}\s*/\s*\d{2,4}(?:\s*[A-Z])?\b")
ADMIN_REF_RE = re.compile(r"\b[A-Za-z]{1,4}\d{0,3}\.\d{1,6}\s*/\s*\d{1,4}(?:#\d+)?\b")
YEAR_SLASH_RE = re.compile(r"\b20\d{2}\s*/\s*\d{3,5}\b")
GERMAN_AZ_SLASH_RE = re.compile(
    r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,6}\s*\d{1,5}\s*/\s*\d{2}(?:\.?[A-Za-z]+)?\b"
)
GERMAN_AZ_DOT_RE = re.compile(
    r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,6}\s*\d{1,5}\.\d{2}(?:\.?[A-Za-z]+)?\b"
)
GERMAN_AZ_DASH_RE = re.compile(
    r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,6}\s*\d{1,5}\s*-\s*\d{2}(?:\.?[A-Za-z]+)?\b"
)

GENERIC_COURT_TOKENS = {
    "vg",
    "ovg",
    "vgh",
    "bverwg",
    "eugh",
    "euaa",
    "lg",
    "ag",
    "sg",
    "lsg",
    "bgh",
    "egmr",
    "eu",
    "b",
    "u",
    "v",
}

COMMON_TITLE_TOKENS = {
    "dokument",
    "einsender",
    "vom",
    "zur",
    "zum",
    "und",
    "der",
    "die",
    "das",
    "des",
    "den",
    "im",
    "in",
    "auf",
    "von",
    "v",
    "u",
    "b",
    "nr",
    "an",
    "mit",
    "fur",
    "eine",
    "einer",
    "bei",
}


def strip_document_ref_markers(text: str) -> str:
    return DOCUMENT_REF_RE.sub(" ", text)


def _extract_best_az_match(citation: str) -> str:
    patterns = [
        EU_CASE_RE,
        ADMIN_REF_RE,
        YEAR_SLASH_RE,
        GERMAN_AZ_SLASH_RE,
        GERMAN_AZ_DOT_RE,
        GERMAN_AZ_DASH_RE,
    ]
    for pattern in patterns:
        matches = list(pattern.finditer(citation))
        if matches:
            return matches[-1].group(0)

    dot_pat = re.compile(r"\b\d{1,3}\.\d{3,5}\b")
    plain_num_pat = re.compile(r"\b\d{5,}\b")
    dot_matches = list(dot_pat.finditer(citation))
    usable = []
    for match in dot_matches:
        left_s, right_s = match.group(0).split(".")
        left = int(left_s)
        right = int(right_s)
        if 1900 <= right <= 2100:
            continue
        if left <= 31 and right <= 12:
            continue
        usable.append(match)
    if usable:
        return usable[-1].group(0)

    plain_num_matches = list(plain_num_pat.finditer(citation))
    if plain_num_matches:
        return plain_num_matches[-1].group(0)
    return ""


def extract_document_refs(text: str) -> list[DocumentRef]:
    lines = text.splitlines()
    refs: list[DocumentRef] = []
    doc_re = re.compile(r"\(Dokument Nr\.\s*(\d{4,5})\s*([a-z])?\)", re.IGNORECASE)
    court_hint_re = re.compile(r"\b(VG|OVG|VGH|LG|BVerwG|BVerfG|EuGH|AG)\b", re.IGNORECASE)
    az_hint_re = re.compile(r"\d{1,3}\s*[A-Za-z]{0,4}\s*\d{1,5}\s*[/.-]\s*\d{2}|\d{1,3}\.\d{3,5}")

    for idx, line in enumerate(lines):
        if "Dokument Nr." not in line:
            continue

        match = doc_re.search(line)
        if not match:
            continue

        doc_number = match.group(1)
        doc_suffix = (match.group(2) or "").lower()
        before = line[: match.start()].strip()
        prev1 = lines[idx - 1].strip() if idx - 1 >= 0 else ""
        prev2 = lines[idx - 2].strip() if idx - 2 >= 0 else ""
        candidate_chunks = [
            before,
            f"{prev1} {before}".strip(),
            f"{prev2} {prev1} {before}".strip(),
        ]

        before_has_structured_citation = bool(
            before and (court_hint_re.search(before) or DATE_RE.search(before) or az_hint_re.search(before))
        )
        prev1_has_structured_citation = bool(
            prev1 and (court_hint_re.search(prev1) or DATE_RE.search(prev1) or az_hint_re.search(prev1))
        )
        prev2_has_structured_citation = bool(
            prev2 and (court_hint_re.search(prev2) or DATE_RE.search(prev2) or az_hint_re.search(prev2))
        )
        before_looks_like_title = len(split_filename_words(before)) >= 4 and not before_has_structured_citation

        def quality_score(chunk: str) -> int:
            chunk = strip_document_ref_markers(chunk)
            score = 0
            if court_hint_re.search(chunk):
                score += 3
            if DATE_RE.search(chunk):
                score += 2
            if az_hint_re.search(chunk):
                score += 2
            if chunk == before and len(split_filename_words(chunk)) >= 4:
                score += 6
            if chunk != before and prev1.rstrip().endswith(("-", "und", "des", "der", "die", "vom", "zur", "zum", "im", "am")):
                score += 7
            score += min(len(chunk), 120) // 40
            return score

        if not before and prev1 and prev2.rstrip().endswith(("und", "-")):
            citation = f"{prev2} {prev1}".strip()
        elif before_looks_like_title and prev1.rstrip().endswith(("und", "-")):
            citation = f"{prev1} {before}".strip()
        elif before_looks_like_title and (prev1_has_structured_citation or prev2_has_structured_citation):
            citation = before
        else:
            citation = max(candidate_chunks, key=quality_score)
        citation = strip_document_ref_markers(citation)
        citation = re.sub(r"\s+", " ", citation).strip(" ,;-")
        refs.append(
            DocumentRef(
                doc_number=doc_number,
                doc_suffix=doc_suffix,
                citation=citation,
                line_no=idx + 1,
            )
        )

    return refs


def extract_az_tokens(citation: str) -> list[str]:
    az_raw = _extract_best_az_match(citation)
    if not az_raw:
        return []
    return [tok for tok in tokenize(az_raw) if len(tok) >= 1]


def extract_court_tokens(citation: str) -> list[str]:
    head = citation.split(",", 1)[0]
    toks = tokenize(head)
    return toks[:3]


def extract_date_variants(citation: str) -> list[str]:
    match = DATE_RE.search(citation)
    if not match:
        return []
    day, month, year = match.group(1), match.group(2), match.group(3)
    return [f"{day} {month} {year}", f"{year} {month} {day}"]


def extract_az_raw(citation: str) -> str:
    return _extract_best_az_match(citation)


def extract_az_phrase(citation: str) -> str:
    az_raw = extract_az_raw(citation)
    return normalize_text(az_raw) if az_raw else ""


def build_title_fallback_tokens(citation: str) -> list[str]:
    text = re.sub(r"\(.*?\)", " ", citation)
    text = re.sub(r"\b[UB]\.\s*v\.", " ", text)
    text = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", " ", text)
    az_raw = extract_az_raw(text)
    if az_raw:
        text = text.replace(az_raw, " ")
    tokens: list[str] = []
    for word in split_filename_words(text):
        lowered = normalize_text(word)
        if len(lowered) <= 2:
            continue
        if lowered in COMMON_TITLE_TOKENS or lowered in GENERIC_COURT_TOKENS:
            continue
        formatted = format_filename_word(word)
        if formatted not in tokens:
            tokens.append(formatted)
    return tokens[:6]
