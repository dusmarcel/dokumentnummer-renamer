import re
from pathlib import Path

from .extract import (
    COMMON_TITLE_TOKENS,
    GENERIC_COURT_TOKENS,
    extract_az_phrase,
    extract_az_tokens,
    extract_court_tokens,
    extract_date_variants,
)
from .models import CandidateDoc, DocumentRef, MatchResult
from .pdf_tools import build_candidate_index
from .text_utils import normalize_text, tokenize


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

    scored: list[tuple[int, int, int, Path]] = []
    for path in files:
        doc = index[path]
        name_hits = sum(1 for tok in citation_tokens if tok in doc.name_tokens)
        content_hits = sum(1 for tok in citation_tokens if tok in doc.content_tokens)
        score = (name_hits * 3) + content_hits
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

    reason = (
        "Titel-Score: "
        f"top={top_score}, second={second_score}, "
        f"name={top_name_hits}, content={top_content_hits}, tokens={token_count}"
    )
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
    az_phrase = extract_az_phrase(ref.citation)
    court_tokens = extract_court_tokens(ref.citation)
    specific_court_tokens = [tok for tok in court_tokens if tok not in GENERIC_COURT_TOKENS]
    date_variants = extract_date_variants(ref.citation)
    files = sorted(index.keys())

    candidates: list[Path] = []
    reason = ""

    if az_tokens:
        num_tokens = [tok for tok in az_tokens if tok.isdigit()]
        alpha_tokens = [tok for tok in az_tokens if tok.isalpha() and len(tok) > 1]

        for path in files:
            doc = index[path]
            if not all(tok in doc.name_tokens for tok in num_tokens):
                continue
            if not all(tok in doc.name_tokens for tok in alpha_tokens):
                continue
            candidates.append(path)

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
            if az_phrase and len(candidates) > 1:
                narrowed = []
                for path in candidates:
                    if az_phrase in index[path].norm_content:
                        narrowed.append(path)
                if narrowed:
                    candidates = narrowed
                    reason += f", AZ-Phrase: {az_phrase}"

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
    else:
        title_fallback = match_by_title_tokens(ref, index, files)
        candidates = title_fallback.matches
        reason = title_fallback.reason

    return MatchResult(ref=ref, matches=sorted(candidates), reason=reason)
