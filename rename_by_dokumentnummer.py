#!/usr/bin/env python3
import argparse
import shutil
import sys
from pathlib import Path

from renamer.deps import run_dependency_route
from renamer.extract import extract_document_refs
from renamer.match import list_candidate_files, match_reference_with_index
from renamer.pdf_tools import build_candidate_index, run_pdftotext
from renamer.rename_ops import rename_files

IGNORE_FILE_NAMES = {
    "ana-zar_1_26_online.pdf",
}


def build_parser() -> argparse.ArgumentParser:
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
        help="Trennzeichen zwischen den Bestandteilen des Ziel-Dateinamens (Standard: '_')",
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
    return parser


def main() -> int:
    parser = build_parser()
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
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    refs = extract_document_refs(text)
    if not refs:
        print("Keine Dokumentnummern gefunden.")
        return 1

    files = list_candidate_files(
        folder,
        source_pdf,
        script_path,
        ignore_names=IGNORE_FILE_NAMES,
    )
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
    return 0 if errors == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
