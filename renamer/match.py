import re
from pathlib import Path

from .extract import (
    COMMON_TITLE_TOKENS,
    EU_CASE_RE,
    GENERIC_COURT_TOKENS,
    extract_az_raw,
    extract_az_phrase,
    extract_az_tokens,
    extract_court_tokens,
    extract_date_variants,
    strip_document_ref_markers,
)
from .models import CandidateDoc, DocumentRef, MatchResult
from .pdf_tools import build_candidate_index
from .text_utils import normalize_text, tokenize

NON_SIGNIFICANT_AZ_ALPHA_TOKENS = {"rs", "nr", "az", "ga"}


def extract_filename_doc_id(path: Path) -> str:
    match = re.match(r"^(\d{4,5}[a-z]?)(?:$|[^A-Za-z0-9])", path.stem, flags=re.IGNORECASE)
    return (match.group(1) or "").lower() if match else ""


def filename_starts_with_doc_id(path: Path, doc_id: str) -> bool:
    normalized_stem = normalize_text(path.stem)
    normalized_doc_id = normalize_text(doc_id)
    return normalized_stem == normalized_doc_id or normalized_stem.startswith(f"{normalized_doc_id} ")


def build_title_match_phrase(citation: str) -> str:
    cleaned = strip_document_ref_markers(citation)
    cleaned = re.sub(r"^\s*Dokument\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*Einsender\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b([UB])\.\s*v\.", " ", cleaned)
    cleaned = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", " ", cleaned)
    tokens = [
        tok
        for tok in tokenize(cleaned)
        if len(tok) > 2 and tok not in COMMON_TITLE_TOKENS and tok not in GENERIC_COURT_TOKENS
    ]
    return " ".join(tokens[:8])


def build_specific_title_phrase(citation: str) -> str:
    cleaned = strip_document_ref_markers(citation)
    cleaned = re.sub(r"^\s*Dokument\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*Einsender\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    tokens = [
        tok
        for tok in tokenize(cleaned)
        if len(tok) > 2 and tok not in COMMON_TITLE_TOKENS and tok not in GENERIC_COURT_TOKENS and not tok.isdigit()
    ]
    if len(tokens) < 4:
        return ""
    return " ".join(tokens[-4:])


def build_literal_tail_phrase(citation: str) -> str:
    cleaned = strip_document_ref_markers(citation)
    cleaned = re.sub(r"^\s*Dokument\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*Einsender\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    normalized = normalize_text(cleaned)
    tokens = normalized.split()
    if len(tokens) < 4:
        return ""
    return " ".join(tokens[-6:])


def path_matches_date(path: Path, date_variants: list[str]) -> bool:
    if not date_variants:
        return False
    normalized_stem = normalize_text(path.stem)
    return any(variant in normalized_stem for variant in date_variants)


def filter_conflicting_prefixed_candidates(candidates: list[Path], doc_id: str) -> list[Path]:
    if len(candidates) <= 1:
        return candidates

    exact = [path for path in candidates if extract_filename_doc_id(path) == doc_id.lower()]
    if exact:
        return exact

    neutral = [path for path in candidates if not extract_filename_doc_id(path)]
    if neutral:
        return neutral

    return []


def reject_single_conflicting_candidate(candidates: list[Path], doc_id: str) -> list[Path]:
    if len(candidates) != 1:
        return candidates
    file_doc_id = extract_filename_doc_id(candidates[0])
    if file_doc_id and file_doc_id != doc_id.lower():
        return []
    return candidates


def match_eu_case_reference(
    az_raw: str,
    date_variants: list[str],
    index: dict[Path, CandidateDoc],
    files: list[Path],
) -> list[Path]:
    if not az_raw or not EU_CASE_RE.search(az_raw):
        return []

    phrase = normalize_text(re.sub(r"\bRs\.?\b", " ", az_raw, flags=re.IGNORECASE))
    candidates = []
    for path in files:
        doc = index[path]
        if phrase in normalize_text(path.stem) or phrase in doc.norm_content:
            candidates.append(path)

    if len(candidates) <= 1:
        return candidates

    narrowed = []
    for path in candidates:
        content = index[path].norm_content
        if any(variant in content or variant in normalize_text(path.stem) for variant in date_variants):
            narrowed.append(path)
    return narrowed if narrowed else candidates


def narrow_by_earliest_az_phrase(
    candidates: list[Path],
    index: dict[Path, CandidateDoc],
    az_phrase: str,
) -> list[Path]:
    if len(candidates) <= 1 or not az_phrase:
        return candidates

    positions: list[tuple[int, Path]] = []
    for path in candidates:
        pos = index[path].norm_content.find(az_phrase)
        if pos >= 0:
            positions.append((pos, path))
    if len(positions) <= 1:
        return candidates

    positions.sort(key=lambda item: item[0])
    best_pos = positions[0][0]
    second_pos = positions[1][0]
    if second_pos - best_pos >= 200:
        return [positions[0][1]]
    return candidates


def match_numeric_filename_fallback(
    az_tokens: list[str],
    index: dict[Path, CandidateDoc],
    files: list[Path],
) -> list[Path]:
    significant_numbers = sorted({tok for tok in az_tokens if tok.isdigit() and len(tok) >= 4})
    if len(significant_numbers) != 1:
        return []

    target_number = significant_numbers[0]
    matches: list[Path] = []
    for path in files:
        doc = index[path]
        if doc.name_tokens == {target_number}:
            matches.append(path)
    return sorted(matches)


def filename_matches_decision_type(path: Path, decision_type: str) -> bool:
    normalized = normalize_text(path.stem)
    tokens = normalized.split()
    token_pairs = list(zip(tokens, tokens[1:]))

    if decision_type == "urteil":
        return "urteil" in normalized or ("u", "v") in token_pairs
    return "beschluss" in normalized or "beweisbeschluss" in normalized or ("b", "v") in token_pairs


def filename_explicitly_marks_decision_type(path: Path, decision_type: str) -> bool:
    return filename_matches_decision_type(path, decision_type)


def match_by_title_tokens(
    ref: DocumentRef,
    index: dict[Path, CandidateDoc],
    files: list[Path],
) -> MatchResult:
    raw_citation_tokens = tokenize(ref.citation)
    citation_tokens = [
        tok
        for tok in raw_citation_tokens
        if len(tok) > 3 and tok not in GENERIC_COURT_TOKENS and tok not in COMMON_TITLE_TOKENS and not tok.isdigit()
    ]
    if raw_citation_tokens:
        first_tok = raw_citation_tokens[0]
        if first_tok.isdigit() and 1 <= len(first_tok) <= 2 and first_tok not in citation_tokens:
            citation_tokens.append(first_tok)

    court_tokens = [tok for tok in extract_court_tokens(ref.citation) if len(tok) > 1 and not tok.isdigit()]
    extra_tokens: list[str] = []
    if re.search(r"\bU\.\s*v\.", ref.citation):
        extra_tokens.append("urteil")
    elif re.search(r"\bB\.\s*v\.", ref.citation):
        extra_tokens.append("beschluss")
    extra_tokens.extend(court_tokens)

    for tok in extra_tokens:
        if tok not in citation_tokens:
            citation_tokens.append(tok)

    if not citation_tokens:
        return MatchResult(ref=ref, matches=[], reason="Kein robustes Aktenzeichen extrahiert")

    date_variants = extract_date_variants(ref.citation)
    title_phrase = build_title_match_phrase(ref.citation)
    specific_title_phrase = build_specific_title_phrase(ref.citation)
    literal_tail_phrase = build_literal_tail_phrase(ref.citation)
    normalized_citation = normalize_text(ref.citation)
    scored: list[tuple[int, int, int, Path]] = []
    for path in files:
        doc = index[path]
        name_hits = sum(1 for tok in citation_tokens if tok in doc.name_tokens)
        content_hits = sum(1 for tok in citation_tokens if tok in doc.content_tokens)
        score = (name_hits * 3) + content_hits
        if title_phrase and title_phrase in doc.norm_content:
            score += 4
        if title_phrase and title_phrase in normalize_text(path.stem):
            score += 3
        if specific_title_phrase and specific_title_phrase in doc.norm_content:
            score += 6
        if specific_title_phrase and specific_title_phrase in normalize_text(path.stem):
            score += 5
        if literal_tail_phrase and literal_tail_phrase in doc.norm_content:
            score += 8
        if literal_tail_phrase and literal_tail_phrase in normalize_text(path.stem):
            score += 6
        if path_matches_date(path, date_variants):
            score += 3
        if filename_starts_with_doc_id(path, ref.doc_id):
            score += 5
        file_doc_id = extract_filename_doc_id(path)
        if file_doc_id and file_doc_id != ref.doc_id.lower():
            score -= 6
        normalized_stem = normalize_text(path.stem)
        if "einsender" in normalized_citation and "antwortschreiben" not in normalized_citation:
            if "schreiben an" in normalized_stem:
                score += 3
            if "europ" in normalized_stem and "kommission" in normalized_stem:
                score -= 2
        if "antwortschreiben" in normalized_citation:
            if "europ" in normalized_stem and "kommission" in normalized_stem:
                score += 4
            if "schreiben an" in normalized_stem:
                score -= 2
        if score > 0:
            scored.append((score, name_hits, content_hits, path))

    if not scored:
        return MatchResult(ref=ref, matches=[], reason="Kein robustes Aktenzeichen extrahiert")

    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3].name.lower()), reverse=True)
    top_score, top_name_hits, top_content_hits, top_path = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1
    second_name_hits = scored[1][1] if len(scored) > 1 else -1

    token_count = len(citation_tokens)
    min_name_hits = 2 if token_count >= 2 else 1
    min_score = 3 if token_count <= 3 else min(8, max(4, token_count))

    candidates: list[Path] = []
    if top_name_hits >= min_name_hits and top_name_hits > second_name_hits:
        candidates = [top_path]
    elif top_score >= min_score and top_score >= second_score + 2:
        candidates = [top_path]
    elif filename_starts_with_doc_id(top_path, ref.doc_id) and top_score >= max(4, second_score + 1):
        candidates = [top_path]

    reason = (
        "Titel-Score: "
        f"top={top_score}, second={second_score}, "
        f"name={top_name_hits}, content={top_content_hits}, tokens={token_count}"
    )
    candidates = filter_conflicting_prefixed_candidates(candidates, ref.doc_id)
    candidates = reject_single_conflicting_candidate(candidates, ref.doc_id)
    return MatchResult(ref=ref, matches=sorted(candidates), reason=reason)


def list_candidate_files(folder: Path, source_pdf: Path, script_path: Path, ignore_names: set[str]) -> list[Path]:
    out: list[Path] = []
    for path in sorted(folder.glob("*.pdf")):
        if path.name.lower() in ignore_names:
            continue
        if path.resolve() == source_pdf.resolve():
            continue
        if path.resolve() == script_path.resolve():
            continue
        out.append(path)
    return out


def match_reference(ref: DocumentRef, files: list[Path]) -> MatchResult:
    return match_reference_with_index(
        ref,
        build_candidate_index(
            files,
            analyze_content=False,
            use_ocr=False,
            ocr_pages=1,
            ocr_dpi=220,
            ocr_lang="deu+eng",
            make_searchable=False,
            searchable_dir=Path(".searchable_pdfs"),
            searchable_force=False,
        ),
    )


def match_reference_with_index(ref: DocumentRef, index: dict[Path, CandidateDoc]) -> MatchResult:
    az_tokens = extract_az_tokens(ref.citation)
    az_raw = extract_az_raw(ref.citation)
    az_phrase = extract_az_phrase(ref.citation)
    court_tokens = extract_court_tokens(ref.citation)
    specific_court_tokens = [tok for tok in court_tokens if tok not in GENERIC_COURT_TOKENS]
    date_variants = extract_date_variants(ref.citation)
    title_phrase = build_title_match_phrase(ref.citation)
    specific_title_phrase = build_specific_title_phrase(ref.citation)
    literal_tail_phrase = build_literal_tail_phrase(ref.citation)
    files = sorted(index.keys())

    candidates: list[Path] = []
    reason = ""

    doc_id_candidates = [path for path in files if filename_starts_with_doc_id(path, ref.doc_id)]
    if len(doc_id_candidates) == 1 and (path_matches_date(doc_id_candidates[0], date_variants) or not az_tokens):
        candidates = doc_id_candidates
        reason = f"Dokumentnummer im Dateinamen: {doc_id_candidates[0].name}"

    if not candidates and (title_phrase or specific_title_phrase or literal_tail_phrase) and not date_variants and not az_raw.startswith("Rs. "):
        exact_title_candidates = []
        for path in files:
            doc = index[path]
            if (
                (literal_tail_phrase and (literal_tail_phrase in normalize_text(path.stem) or literal_tail_phrase in doc.norm_content))
                or
                (specific_title_phrase and (specific_title_phrase in normalize_text(path.stem) or specific_title_phrase in doc.norm_content))
                or (title_phrase and (title_phrase in normalize_text(path.stem) or title_phrase in doc.norm_content))
            ):
                exact_title_candidates.append(path)
        exact_title_candidates = filter_conflicting_prefixed_candidates(exact_title_candidates, ref.doc_id)
        exact_title_candidates = reject_single_conflicting_candidate(exact_title_candidates, ref.doc_id)
        if exact_title_candidates:
            candidates = exact_title_candidates
            reason = f"Titelphrase: {literal_tail_phrase or specific_title_phrase or title_phrase}"

    if not candidates:
        eu_case_candidates = match_eu_case_reference(az_raw, date_variants, index, files)
        if eu_case_candidates:
            candidates = filter_conflicting_prefixed_candidates(eu_case_candidates, ref.doc_id)
            candidates = reject_single_conflicting_candidate(candidates, ref.doc_id)
            if candidates:
                reason = f"EU-Aktenzeichen: {az_raw}"
            else:
                return MatchResult(ref=ref, matches=[], reason=f"EU-Aktenzeichen ohne exakten Treffer: {az_raw}")
        elif az_raw and EU_CASE_RE.search(az_raw):
            return MatchResult(ref=ref, matches=[], reason=f"EU-Aktenzeichen ohne exakten Treffer: {az_raw}")

    if az_tokens and not candidates:
        num_tokens = [tok for tok in az_tokens if tok.isdigit()]
        alpha_tokens = [
            tok
            for tok in az_tokens
            if tok.isalpha() and len(tok) > 1 and tok not in NON_SIGNIFICANT_AZ_ALPHA_TOKENS
        ]

        for path in files:
            doc = index[path]
            if not all(tok in doc.name_tokens for tok in num_tokens):
                continue
            if not all(tok in doc.name_tokens for tok in alpha_tokens):
                continue
            candidates.append(path)

        if az_phrase and candidates:
            exact_phrase_matches = []
            for path in candidates:
                doc = index[path]
                if az_phrase in normalize_text(path.stem) or az_phrase in doc.norm_content:
                    exact_phrase_matches.append(path)
            if exact_phrase_matches:
                candidates = exact_phrase_matches

        candidates = narrow_by_earliest_az_phrase(candidates, index, az_phrase)

        decision_type = ""
        if re.search(r"\bU\.\s*v\.", ref.citation):
            decision_type = "urteil"
        elif re.search(r"\bB\.\s*v\.", ref.citation):
            decision_type = "beschluss"

        if decision_type and len(candidates) > 1:
            narrowed: list[Path] = []
            for path in candidates:
                if decision_type == "urteil":
                    normalized = normalize_text(path.stem)
                    if filename_matches_decision_type(path, "urteil") or (
                        " beschluss " not in f" {normalized} "
                        and "beweisbeschluss" not in normalized
                        and not filename_explicitly_marks_decision_type(path, "beschluss")
                    ):
                        narrowed.append(path)
                else:
                    if filename_matches_decision_type(path, "beschluss"):
                        narrowed.append(path)
            if narrowed:
                candidates = narrowed

        reason = f"AZ-Tokens: {' '.join(az_tokens)}"

        if specific_court_tokens and len(candidates) > 1:
            narrowed = []
            for path in candidates:
                normalized = normalize_text(path.stem)
                if any(tok in normalized.split() for tok in specific_court_tokens):
                    narrowed.append(path)
            if narrowed:
                candidates = narrowed
                reason += f", Gerichts-Tokens: {' '.join(specific_court_tokens)}"

        candidates = filter_conflicting_prefixed_candidates(candidates, ref.doc_id)
        candidates = reject_single_conflicting_candidate(candidates, ref.doc_id)

        if len(candidates) == 0:
            numeric_filename_matches = match_numeric_filename_fallback(az_tokens, index, files)
            if numeric_filename_matches:
                candidates = numeric_filename_matches
                reason = f"Numerischer Dateiname: {numeric_filename_matches[0].stem}"

        if len(candidates) == 0:
            for path in files:
                doc = index[path]
                if not doc.content_tokens:
                    continue
                if not all(tok in doc.content_tokens for tok in num_tokens):
                    continue
                if not all(tok in doc.content_tokens for tok in alpha_tokens):
                    continue
                candidates.append(path)

            reason = f"Inhalt-AZ-Tokens: {' '.join(az_tokens)}"
            if az_phrase and candidates:
                narrowed = []
                for path in candidates:
                    if az_phrase in normalize_text(path.stem) or az_phrase in index[path].norm_content:
                        narrowed.append(path)
                if narrowed:
                    candidates = narrowed
                    reason += f", AZ-Phrase: {az_phrase}"

            candidates = narrow_by_earliest_az_phrase(candidates, index, az_phrase)
            candidates = filter_conflicting_prefixed_candidates(candidates, ref.doc_id)
            candidates = reject_single_conflicting_candidate(candidates, ref.doc_id)

            if specific_court_tokens and len(candidates) > 1:
                narrowed = []
                for path in candidates:
                    content_tokens = index[path].content_tokens
                    if any(tok in content_tokens for tok in specific_court_tokens):
                        narrowed.append(path)
                if narrowed:
                    candidates = narrowed
                    reason += f", Gerichts-Tokens: {' '.join(specific_court_tokens)}"

            if date_variants and len(candidates) > 1:
                narrowed = []
                for path in candidates:
                    content = index[path].norm_content
                    if any(variant in content for variant in date_variants):
                        narrowed.append(path)
                if narrowed:
                    candidates = narrowed
                    reason += f", Datum: {date_variants[0]}"

        if len(candidates) == 0:
            title_fallback = match_by_title_tokens(ref, index, files)
            if title_fallback.matches:
                title_reason = title_fallback.reason
                prefix = reason or "AZ-Treffer fehlt"
                return MatchResult(
                    ref=ref,
                    matches=title_fallback.matches,
                    reason=f"{prefix} -> Fallback {title_reason}",
                )
    elif not candidates:
        title_fallback = match_by_title_tokens(ref, index, files)
        candidates = title_fallback.matches
        reason = title_fallback.reason

    return MatchResult(ref=ref, matches=sorted(candidates), reason=reason)
