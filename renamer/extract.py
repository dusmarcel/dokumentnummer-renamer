import re

from .models import DocumentRef
from .text_utils import format_filename_word, normalize_text, split_filename_words, tokenize

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

        def quality_score(chunk: str) -> int:
            score = 0
            if court_hint_re.search(chunk):
                score += 3
            if re.search(r"\d{2}\.\d{2}\.\d{4}", chunk):
                score += 2
            if az_hint_re.search(chunk):
                score += 2
            score += min(len(chunk), 120) // 40
            return score

        citation = max(candidate_chunks, key=quality_score)
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
    slash_pat = r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*/\s*\d{2}(?:\.[A-Za-z])?\b"
    dash_pat = r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*-\s*\d{2}(?:\.[A-Za-z])?\b"
    dot_pat = r"\b\d{1,3}\.\d{3,5}\b"
    plain_num_pat = r"\b\d{5,}\b"

    slash_matches = list(re.finditer(slash_pat, citation))
    if slash_matches:
        az_raw = slash_matches[-1].group(0)
        return [tok for tok in tokenize(az_raw) if len(tok) >= 1]

    dash_matches = list(re.finditer(dash_pat, citation))
    if dash_matches:
        az_raw = dash_matches[-1].group(0)
        return [tok for tok in tokenize(az_raw) if len(tok) >= 1]

    dot_matches = list(re.finditer(dot_pat, citation))
    if not dot_matches:
        plain_num_matches = list(re.finditer(plain_num_pat, citation))
        if not plain_num_matches:
            return []
        az_raw = plain_num_matches[-1].group(0)
        return [tok for tok in tokenize(az_raw) if len(tok) >= 1]

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
    if not usable:
        plain_num_matches = list(re.finditer(plain_num_pat, citation))
        if not plain_num_matches:
            return []
        az_raw = plain_num_matches[-1].group(0)
        return [tok for tok in tokenize(az_raw) if len(tok) >= 1]
    az_raw = usable[-1].group(0)
    return [tok for tok in tokenize(az_raw) if len(tok) >= 1]


def extract_court_tokens(citation: str) -> list[str]:
    head = citation.split(",", 1)[0]
    toks = tokenize(head)
    return toks[:3]


def extract_date_variants(citation: str) -> list[str]:
    match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", citation)
    if not match:
        return []
    day, month, year = match.group(1), match.group(2), match.group(3)
    return [f"{day} {month} {year}", f"{year} {month} {day}"]


def extract_az_raw(citation: str) -> str:
    patterns = [
        r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*/\s*\d{2}(?:\.[A-Za-z])?\b",
        r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*-\s*\d{2}(?:\.[A-Za-z])?\b",
        r"\b\d{1,3}\.\d{3,5}\b",
        r"\b\d{5,}\b",
    ]
    for pattern in patterns:
        matches = list(re.finditer(pattern, citation))
        if matches:
            return matches[-1].group(0)
    return ""


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
