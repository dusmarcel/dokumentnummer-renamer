#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

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

IGNORE_FILE_NAMES = {
    "ana-zar_1_26_online.pdf",
}

MIN_PYTHON = (3, 10)


@dataclass
class DocumentRef:
    doc_number: str
    doc_suffix: str
    citation: str
    line_no: int

    @property
    def doc_id(self) -> str:
        return f"{self.doc_number}{self.doc_suffix}"


@dataclass
class MatchResult:
    ref: DocumentRef
    matches: List[Path]
    reason: str


@dataclass
class CandidateDoc:
    path: Path
    name_tokens: set[str]
    content_tokens: set[str]
    norm_content: str


@dataclass
class DependencyStatus:
    tool: str
    required: bool
    found_path: str | None
    note: str


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> List[str]:
    n = normalize_text(text)
    return n.split() if n else []


def check_python_version() -> bool:
    return sys.version_info >= MIN_PYTHON


def collect_dependency_status() -> List[DependencyStatus]:
    return [
        DependencyStatus(
            tool="python3.10+",
            required=True,
            found_path=sys.executable if check_python_version() else None,
            note=f"Version: {sys.version.split()[0]}",
        ),
        DependencyStatus(
            tool="pdftotext",
            required=True,
            found_path=shutil.which("pdftotext"),
            note="Aus poppler-utils/poppler",
        ),
        DependencyStatus(
            tool="pdftoppm",
            required=False,
            found_path=shutil.which("pdftoppm"),
            note="Benötigt für --ocr",
        ),
        DependencyStatus(
            tool="tesseract",
            required=False,
            found_path=shutil.which("tesseract"),
            note="Benötigt für --ocr",
        ),
        DependencyStatus(
            tool="ocrmypdf",
            required=False,
            found_path=shutil.which("ocrmypdf"),
            note="Benötigt für --make-searchable",
        ),
    ]


def print_dependency_status(statuses: List[DependencyStatus]) -> None:
    print("Abhängigkeitsprüfung:")
    for dep in statuses:
        kind = "PFLICHT" if dep.required else "OPTIONAL"
        state = "OK" if dep.found_path else "FEHLT"
        path = dep.found_path if dep.found_path else "-"
        print(f"- [{state}] {dep.tool:<11} ({kind}) | {dep.note} | {path}")


def required_dependencies_ok(statuses: List[DependencyStatus]) -> bool:
    return all(dep.found_path for dep in statuses if dep.required)


def detect_package_manager() -> str | None:
    for manager in ("apt-get", "dnf", "pacman", "zypper", "brew"):
        if shutil.which(manager):
            return manager
    return None


def detect_aur_helper() -> str | None:
    for helper in ("yay", "paru"):
        if shutil.which(helper):
            return helper
    return None


def build_install_steps(manager: str, include_optional: bool) -> List[List[str]]:
    needs_elevation = manager in {"apt-get", "dnf", "pacman", "zypper"}
    if needs_elevation and hasattr(os, "geteuid") and os.geteuid() != 0:
        if shutil.which("sudo") is None:
            print("Hinweis: 'sudo' nicht gefunden. Installation könnte wegen fehlender Rechte fehlschlagen.")
            prefix: List[str] = []
        else:
            prefix = ["sudo"]
    else:
        prefix = []

    if manager == "apt-get":
        packages = ["poppler-utils"]
        if include_optional:
            packages.extend(["tesseract-ocr", "ocrmypdf"])
        return [
            [*prefix, "apt-get", "update"],
            [*prefix, "apt-get", "install", "-y", *packages],
        ]
    if manager == "dnf":
        packages = ["poppler-utils"]
        if include_optional:
            packages.extend(["tesseract", "ocrmypdf"])
        return [[*prefix, "dnf", "install", "-y", *packages]]
    if manager == "pacman":
        packages = ["poppler"]
        if include_optional:
            packages.append("tesseract")
        steps = [[*prefix, "pacman", "-S", "--needed", *packages]]
        if include_optional:
            aur_helper = detect_aur_helper()
            if aur_helper:
                steps.append([aur_helper, "-S", "--needed", "ocrmypdf"])
            else:
                print(
                    "Hinweis: Für Arch Linux liegt 'ocrmypdf' typischerweise im AUR. "
                    "Bitte installiere einen AUR-Helper wie 'yay' oder 'paru'."
                )
        return steps
    if manager == "zypper":
        packages = ["poppler-tools"]
        if include_optional:
            packages.extend(["tesseract-ocr", "ocrmypdf"])
        return [[*prefix, "zypper", "install", "-y", *packages]]
    if manager == "brew":
        packages = ["poppler"]
        if include_optional:
            packages.extend(["tesseract", "ocrmypdf"])
        return [["brew", "install", *packages]]
    return []


def run_dependency_route(install: bool, include_optional: bool) -> int:
    statuses = collect_dependency_status()
    print_dependency_status(statuses)
    print("---")
    required_ok = required_dependencies_ok(statuses)
    if required_ok:
        print("Pflichtabhängigkeiten: OK")
    else:
        print("Pflichtabhängigkeiten: FEHLEN")

    if not install:
        return 0 if required_ok else 2

    manager = detect_package_manager()
    if manager is None:
        print("Kein unterstützter Paketmanager gefunden (apt-get/dnf/pacman/zypper/brew).")
        print("Bitte installiere manuell: poppler-utils bzw. poppler.")
        if include_optional:
            print("Optional zusätzlich: tesseract, ocrmypdf")
        return 2

    steps = build_install_steps(manager, include_optional)
    if not steps:
        print(f"Keine Installationsschritte für Paketmanager '{manager}' verfügbar.")
        return 2

    print(f"Installationsversuch via {manager}:")
    for step in steps:
        print(f"$ {' '.join(step)}")
        proc = subprocess.run(step, check=False)
        if proc.returncode != 0:
            print(f"Fehler bei Installationsschritt (Exit {proc.returncode}).", file=sys.stderr)
            return proc.returncode

    print("---")
    print("Erneute Prüfung nach Installation:")
    post = collect_dependency_status()
    print_dependency_status(post)
    return 0 if required_dependencies_ok(post) else 2


def run_pdftotext(pdf_path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext ist nicht installiert oder nicht im PATH.")
    cmd = ["pdftotext", str(pdf_path), "-"]
    proc = subprocess.run(cmd, check=False, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"pdftotext fehlgeschlagen: {stderr.strip()}")
    return proc.stdout.decode("utf-8", errors="ignore")


def run_ocr_text(pdf_path: Path, ocr_pages: int, ocr_dpi: int, ocr_lang: str) -> str:
    if shutil.which("tesseract") is None:
        raise RuntimeError("OCR aktiviert, aber 'tesseract' ist nicht installiert.")
    if shutil.which("pdftoppm") is None:
        raise RuntimeError("OCR aktiviert, aber 'pdftoppm' ist nicht installiert.")

    with tempfile.TemporaryDirectory(prefix="doc_ocr_") as tmp:
        prefix = Path(tmp) / "page"
        render_cmd = [
            "pdftoppm",
            "-r",
            str(ocr_dpi),
            "-f",
            "1",
            "-l",
            str(max(1, ocr_pages)),
            "-png",
            str(pdf_path),
            str(prefix),
        ]
        render = subprocess.run(render_cmd, check=False, capture_output=True)
        if render.returncode != 0:
            stderr = render.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"pdftoppm fehlgeschlagen: {stderr.strip()}")

        pages = sorted(Path(tmp).glob("page-*.png"))
        if not pages:
            return ""

        chunks: List[str] = []
        for img in pages:
            ocr_cmd = ["tesseract", str(img), "stdout", "-l", ocr_lang, "--psm", "6"]
            proc = subprocess.run(ocr_cmd, check=False, capture_output=True)
            if proc.returncode != 0:
                # Ignore individual OCR failures to keep batch robust.
                continue
            chunks.append(proc.stdout.decode("utf-8", errors="ignore"))
        return "\n".join(chunks)


def build_searchable_pdf(
    src_pdf: Path,
    out_dir: Path,
    ocr_lang: str,
    force: bool,
) -> Path:
    if shutil.which("ocrmypdf") is None:
        raise RuntimeError("Durchsuchbare PDFs benötigen 'ocrmypdf', ist aber nicht installiert.")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{src_pdf.stem}.searchable.pdf"

    if out_pdf.exists() and not force and out_pdf.stat().st_mtime >= src_pdf.stat().st_mtime:
        return out_pdf

    cmd = [
        "ocrmypdf",
        "--skip-text",
        "--optimize",
        "0",
        "-l",
        ocr_lang,
        str(src_pdf),
        str(out_pdf),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ocrmypdf fehlgeschlagen für {src_pdf.name}: {stderr.strip()}")
    return out_pdf


def build_candidate_index(
    files: Iterable[Path],
    analyze_content: bool,
    use_ocr: bool,
    ocr_pages: int,
    ocr_dpi: int,
    ocr_lang: str,
    make_searchable: bool,
    searchable_dir: Path,
    searchable_force: bool,
) -> dict[Path, CandidateDoc]:
    index: dict[Path, CandidateDoc] = {}
    for p in files:
        name_tokens = set(tokenize(p.stem))
        content_tokens: set[str] = set()
        norm_content = ""
        content_source = p

        if make_searchable:
            try:
                content_source = build_searchable_pdf(
                    p,
                    out_dir=searchable_dir,
                    ocr_lang=ocr_lang,
                    force=searchable_force,
                )
            except RuntimeError:
                content_source = p

        if analyze_content:
            try:
                txt = run_pdftotext(content_source)
            except RuntimeError:
                txt = ""
            # Fallback to OCR if no extractable text (typical scanned/image PDFs).
            if use_ocr and len(normalize_text(txt)) < 80:
                try:
                    ocr_txt = run_ocr_text(
                        content_source,
                        ocr_pages=ocr_pages,
                        ocr_dpi=ocr_dpi,
                        ocr_lang=ocr_lang,
                    )
                    if len(normalize_text(ocr_txt)) > len(normalize_text(txt)):
                        txt = ocr_txt
                except RuntimeError:
                    pass
            norm_content = normalize_text(txt)
            content_tokens = set(norm_content.split()) if norm_content else set()

        index[p] = CandidateDoc(
            path=p,
            name_tokens=name_tokens,
            content_tokens=content_tokens,
            norm_content=norm_content,
        )
    return index


def extract_document_refs(text: str) -> List[DocumentRef]:
    lines = text.splitlines()
    refs: List[DocumentRef] = []
    doc_re = re.compile(r"\(Dokument Nr\.\s*(\d{4,5})\s*([a-z])?\)", re.IGNORECASE)
    court_hint_re = re.compile(r"\b(VG|OVG|VGH|LG|BVerwG|BVerfG|EuGH|AG)\b", re.IGNORECASE)
    az_hint_re = re.compile(r"\d{1,3}\s*[A-Za-z]{0,4}\s*\d{1,5}\s*[/.-]\s*\d{2}|\d{1,3}\.\d{3,5}")

    for idx, line in enumerate(lines):
        if "Dokument Nr." not in line:
            continue

        m = doc_re.search(line)
        if not m:
            continue

        doc_number = m.group(1)
        doc_suffix = (m.group(2) or "").lower()
        before = line[: m.start()].strip()
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


def extract_az_tokens(citation: str) -> List[str]:
    slash_pat = r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*/\s*\d{2}(?:\.[A-Za-z])?\b"
    dash_pat = r"\b(?:[A-Za-z]{1,4}\s+)?\d{1,3}\s*[A-Za-z]{1,4}\s*\d{1,5}\s*-\s*\d{2}(?:\.[A-Za-z])?\b"
    dot_pat = r"\b\d{1,3}\.\d{3,5}\b"

    slash_matches = list(re.finditer(slash_pat, citation))
    if slash_matches:
        az_raw = slash_matches[-1].group(0)
        return [t for t in tokenize(az_raw) if len(t) >= 1]

    dash_matches = list(re.finditer(dash_pat, citation))
    if dash_matches:
        az_raw = dash_matches[-1].group(0)
        return [t for t in tokenize(az_raw) if len(t) >= 1]

    dot_matches = list(re.finditer(dot_pat, citation))
    if not dot_matches:
        return []

    # Dot-only references can collide with dates; filter obvious date fragments.
    usable = []
    for m in dot_matches:
        left_s, right_s = m.group(0).split(".")
        left = int(left_s)
        right = int(right_s)
        # Drop obvious date fragments like 09.2025 or 19.09.
        if 1900 <= right <= 2100:
            continue
        if left <= 31 and right <= 12:
            continue
        usable.append(m)
    if not usable:
        return []
    az_raw = usable[-1].group(0)
    az_tokens = [t for t in tokenize(az_raw) if len(t) >= 1]
    return az_tokens


def extract_court_tokens(citation: str) -> List[str]:
    head = citation.split(",", 1)[0]
    toks = tokenize(head)
    return toks[:3]


def extract_date_variants(citation: str) -> List[str]:
    m = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", citation)
    if not m:
        return []
    d, mth, y = m.group(1), m.group(2), m.group(3)
    return [f"{d} {mth} {y}", f"{y} {mth} {d}"]


def list_candidate_files(folder: Path, source_pdf: Path, script_path: Path) -> List[Path]:
    out: List[Path] = []
    for p in sorted(folder.glob("*.pdf")):
        if p.name.lower() in IGNORE_FILE_NAMES:
            continue
        if p.resolve() == source_pdf.resolve():
            continue
        if p.resolve() == script_path.resolve():
            continue
        out.append(p)
    return out


def match_reference(ref: DocumentRef, files: Iterable[Path]) -> MatchResult:
    return match_reference_with_index(ref, build_candidate_index(files, analyze_content=False))


def match_reference_with_index(ref: DocumentRef, index: dict[Path, CandidateDoc]) -> MatchResult:
    az_tokens = extract_az_tokens(ref.citation)
    court_tokens = extract_court_tokens(ref.citation)
    specific_court_tokens = [t for t in court_tokens if t not in GENERIC_COURT_TOKENS]
    date_variants = extract_date_variants(ref.citation)
    files = sorted(index.keys())

    candidates: List[Path] = []
    reason = ""

    if az_tokens:
        num_tokens = [t for t in az_tokens if t.isdigit()]
        alpha_tokens = [t for t in az_tokens if t.isalpha() and len(t) > 1]

        for p in files:
            doc = index[p]
            if not all(tok in doc.name_tokens for tok in num_tokens):
                continue
            if not all(tok in doc.name_tokens for tok in alpha_tokens):
                continue
            candidates.append(p)

        decision_type = ""
        if re.search(r"\bU\.\s*v\.", ref.citation):
            decision_type = "urteil"
        elif re.search(r"\bB\.\s*v\.", ref.citation):
            decision_type = "beschluss"

        if decision_type and len(candidates) > 1:
            narrowed: List[Path] = []
            for p in candidates:
                n = normalize_text(p.stem)
                if decision_type == "urteil":
                    if "urteil" in n or (" beschluss " not in f" {n} " and "beweisbeschluss" not in n):
                        narrowed.append(p)
                else:
                    if "beschluss" in n or "beweisbeschluss" in n:
                        narrowed.append(p)
            if narrowed:
                candidates = narrowed

        reason = f"AZ-Tokens: {' '.join(az_tokens)}"

        if specific_court_tokens and len(candidates) > 1:
            narrowed = []
            for p in candidates:
                n = normalize_text(p.stem)
                if any(tok in n.split() for tok in specific_court_tokens):
                    narrowed.append(p)
            if narrowed:
                candidates = narrowed
                reason += f", Gerichts-Tokens: {' '.join(specific_court_tokens)}"

        if len(candidates) == 0:
            for p in files:
                doc = index[p]
                if not doc.content_tokens:
                    continue
                if not all(tok in doc.content_tokens for tok in num_tokens):
                    continue
                if not all(tok in doc.content_tokens for tok in alpha_tokens):
                    continue
                candidates.append(p)

            reason = f"Inhalt-AZ-Tokens: {' '.join(az_tokens)}"
            if specific_court_tokens and len(candidates) > 1:
                narrowed = []
                for p in candidates:
                    content_tokens = index[p].content_tokens
                    if any(tok in content_tokens for tok in specific_court_tokens):
                        narrowed.append(p)
                if narrowed:
                    candidates = narrowed
                    reason += f", Gerichts-Tokens: {' '.join(specific_court_tokens)}"

            if date_variants and len(candidates) > 1:
                narrowed = []
                for p in candidates:
                    content = index[p].norm_content
                    if any(v in content for v in date_variants):
                        narrowed.append(p)
                if narrowed:
                    candidates = narrowed
                    reason += f", Datum: {date_variants[0]}"
    else:
        # Without robust case number, use stricter title matching with unique top score.
        citation_tokens = [
            t
            for t in tokenize(ref.citation)
            if len(t) > 3 and t not in GENERIC_COURT_TOKENS and t not in COMMON_TITLE_TOKENS and not t.isdigit()
        ]
        if not citation_tokens:
            return MatchResult(ref=ref, matches=[], reason="Kein robustes Aktenzeichen extrahiert")

        scored: List[tuple[int, Path]] = []
        for p in files:
            doc = index[p]
            if not doc.content_tokens:
                continue
            score = sum(1 for t in citation_tokens if t in doc.content_tokens)
            if score > 0:
                scored.append((score, p))

        if not scored:
            return MatchResult(ref=ref, matches=[], reason="Kein robustes Aktenzeichen extrahiert")

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]
        second_score = scored[1][0] if len(scored) > 1 else -1

        # Only accept if the top hit is clearly better and meaningful.
        if top_score >= 6 and top_score >= second_score + 2:
            candidates = [scored[0][1]]
        else:
            candidates = []
        reason = f"Inhaltstitel-Score: top={top_score}, second={second_score}, tokens={len(citation_tokens)}"

    return MatchResult(ref=ref, matches=sorted(candidates), reason=reason)


def rename_files(matches: List[MatchResult], separator: str, apply: bool) -> int:
    errors = 0
    already_assigned: dict[Path, str] = {}

    for result in matches:
        ref = result.ref
        doc_id = ref.doc_id
        if len(result.matches) == 0:
            print(
                f"[FEHLT] Dokument Nr. {doc_id}: keine passende Datei gefunden | '{ref.citation}'"
            )
            errors += 1
            continue

        if len(result.matches) > 1:
            print(f"[DOPPELT] Dokument Nr. {doc_id}: mehrere Treffer")
            for p in result.matches:
                print(f"         - {p.name}")
            errors += 1
            continue

        src = result.matches[0]
        if src in already_assigned:
            if already_assigned[src] != doc_id:
                print(
                    f"[DOPPELT] Datei bereits Dokument Nr. {already_assigned[src]} zugeordnet: {src.name} (neu: {doc_id})"
                )
                errors += 1
                continue
            print(f"[OK] Bereits derselben Dokumentnummer zugeordnet: {src.name}")
            continue
        already_assigned[src] = doc_id

        if src.name.startswith(f"{doc_id}{separator}"):
            print(f"[OK] Bereits umbenannt: {src.name}")
            continue

        dst = src.with_name(f"{doc_id}{separator}{src.name}")
        if dst.exists():
            print(
                f"[KONFLIKT] Ziel existiert bereits für Dokument Nr. {doc_id}: {dst.name}"
            )
            errors += 1
            continue

        if apply:
            src.rename(dst)
            print(f"[UMBENANNT] {src.name} -> {dst.name}")
        else:
            print(f"[DRY-RUN] {src.name} -> {dst.name}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Liest ANA-ZAR-PDF, extrahiert '(Dokument Nr. ...)'-Verweise und "
            "benennt passende PDF-Dateien im Ordner um."
        )
    )
    parser.add_argument(
        "--source-pdf",
        default="ANA-ZAR_1_26_Online.pdf",
        help="Quelle mit den Dokument-Verweisen (Standard: ANA-ZAR_1_26_Online.pdf)",
    )
    parser.add_argument(
        "--folder",
        default=".",
        help="Ordner mit den umzubenennenden Dateien (Standard: aktueller Ordner)",
    )
    parser.add_argument(
        "--separator",
        default="_",
        help="Trennzeichen zwischen Dokumentnummer und Originalname (Standard: '_')",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Umbennungen wirklich durchführen (ohne diese Option nur Dry-Run)",
    )
    parser.add_argument(
        "--no-content",
        action="store_true",
        help="Nur Dateinamen verwenden (keine Analyse der PDF-Inhalte).",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="OCR-Fallback für Bild-PDFs aktivieren (benötigt tesseract + pdftoppm).",
    )
    parser.add_argument(
        "--ocr-pages",
        type=int,
        default=4,
        help="Anzahl Seiten pro PDF für OCR-Fallback (Standard: 4).",
    )
    parser.add_argument(
        "--ocr-dpi",
        type=int,
        default=220,
        help="DPI beim Rendern für OCR (Standard: 220).",
    )
    parser.add_argument(
        "--ocr-lang",
        default="deu+eng",
        help="Tesseract-Sprachen (Standard: deu+eng).",
    )
    parser.add_argument(
        "--make-searchable",
        action="store_true",
        help="Erzeugt dauerhaft durchsuchbare PDFs (benötigt ocrmypdf).",
    )
    parser.add_argument(
        "--searchable-dir",
        default=".searchable_pdfs",
        help="Zielordner für erzeugte durchsuchbare PDFs (Standard: .searchable_pdfs).",
    )
    parser.add_argument(
        "--searchable-force",
        action="store_true",
        help="Durchsuchbare PDFs neu erzeugen, auch wenn sie bereits vorhanden sind.",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Prüft Pflicht- und optionale Abhängigkeiten und beendet sich danach.",
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Versucht fehlende Abhängigkeiten über den Paketmanager zu installieren.",
    )
    parser.add_argument(
        "--with-optional-deps",
        action="store_true",
        help="Installiert bei --install-deps auch optionale OCR-Abhängigkeiten.",
    )

    args = parser.parse_args()

    if args.check_deps or args.install_deps:
        return run_dependency_route(
            install=args.install_deps,
            include_optional=args.with_optional_deps,
        )

    folder = Path(args.folder).resolve()
    source_pdf = (folder / args.source_pdf).resolve()
    script_path = Path(__file__).resolve()

    if not source_pdf.exists():
        print(f"Fehler: Quelle nicht gefunden: {source_pdf}", file=sys.stderr)
        return 2

    try:
        text = run_pdftotext(source_pdf)
    except RuntimeError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2

    refs = extract_document_refs(text)
    if not refs:
        print("Keine Dokumentnummern gefunden.")
        return 1

    files = list_candidate_files(folder, source_pdf, script_path)
    if not files:
        print("Keine PDF-Dateien zum Umbenennen gefunden.")
        return 1

    print(f"Gefundene Dokumentverweise: {len(refs)}")
    print(f"PDF-Kandidaten im Ordner: {len(files)}")
    print(f"Modus: {'APPLY' if args.apply else 'DRY-RUN'}")
    analyze_content = not args.no_content
    print(f"Inhaltsanalyse: {'AN' if analyze_content else 'AUS'}")
    print(f"OCR-Fallback: {'AN' if args.ocr else 'AUS'}")
    print(f"Searchable-PDFs: {'AN' if args.make_searchable else 'AUS'}")
    if args.ocr and shutil.which("tesseract") is None:
        print("[HINWEIS] OCR aktiviert, aber 'tesseract' fehlt im PATH. OCR-Fallback wird übersprungen.")
    if args.make_searchable and shutil.which("ocrmypdf") is None:
        print("[HINWEIS] 'ocrmypdf' fehlt im PATH. Durchsuchbare PDFs werden nicht erzeugt.")

    index = build_candidate_index(
        files,
        analyze_content=analyze_content,
        use_ocr=args.ocr,
        ocr_pages=max(1, args.ocr_pages),
        ocr_dpi=max(120, args.ocr_dpi),
        ocr_lang=args.ocr_lang,
        make_searchable=args.make_searchable,
        searchable_dir=(folder / args.searchable_dir).resolve(),
        searchable_force=args.searchable_force,
    )
    match_results = [match_reference_with_index(ref, index) for ref in refs]
    errors = rename_files(match_results, args.separator, args.apply)

    print("---")
    print(f"Verarbeitet: {len(match_results)}")
    print(f"Fehler/Warnungen: {errors}")

    # Non-zero if something could not be matched uniquely.
    return 0 if errors == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
