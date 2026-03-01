import re
from pathlib import Path

from .extract import build_title_fallback_tokens, extract_az_raw
from .models import DocumentRef
from .text_utils import format_filename_word, split_filename_words


def build_target_filename(ref: DocumentRef, src: Path, separator: str) -> str:
    parts: list[str] = [ref.doc_id]

    head = re.sub(r"\(.*?\)", " ", ref.citation.split(",", 1)[0]).strip()
    if re.match(r"^(VG|OVG|VGH|LG|AG|SG|LSG|BVerwG|BVerfG|BGH|EuGH|EuG|EGMR)\b", head, re.IGNORECASE):
        for word in split_filename_words(head):
            formatted = format_filename_word(word)
            if formatted not in parts:
                parts.append(formatted)

    decision_match = re.search(r"\b([UB])\.\s*v\.", ref.citation)
    if decision_match:
        parts.extend([decision_match.group(1).upper(), "v"])

    date_match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", ref.citation)
    if date_match:
        parts.extend([date_match.group(1), date_match.group(2), date_match.group(3)])

    az_raw = extract_az_raw(ref.citation)
    if az_raw:
        for word in split_filename_words(az_raw):
            formatted = format_filename_word(word)
            if formatted not in parts:
                parts.append(formatted)

    if len(parts) == 1:
        parts.extend(build_title_fallback_tokens(ref.citation))

    if len(parts) == 1:
        for word in split_filename_words(src.stem):
            formatted = format_filename_word(word)
            if formatted not in parts:
                parts.append(formatted)

    filename = separator.join(parts)
    filename = re.sub(rf"{re.escape(separator)}+", separator, filename).strip(separator)
    return f"{filename}{src.suffix.lower()}"
