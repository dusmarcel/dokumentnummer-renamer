#!/usr/bin/env python3
"""
Rename PDF files by prepending their Dokumentnummer from an ANA-ZAR source PDF.

Uses Gemini API to extract document references and match them to candidate PDFs.
Uploads trimmed versions (first 3 + last page) of each candidate PDF so Gemini
can read the actual content for matching.

Requires: GEMINI_API_KEY environment variable.
"""

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

import pikepdf
from google import genai
from google.genai import types
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic models for structured Gemini output
# ---------------------------------------------------------------------------

class FileMatch(BaseModel):
    dokument_nr: str   # e.g. "4224"
    suffix: str        # e.g. "b" or "" if none
    filename: str      # matched filename from the list, or "" if no match


class MatchingResult(BaseModel):
    matches: list[FileMatch]


# ---------------------------------------------------------------------------
# PDF trimming
# ---------------------------------------------------------------------------

def trim_pdf(source: Path, first_n: int = 3, tmp_dir: Path | None = None) -> Path:
    """Create a trimmed PDF with first N pages + last page.
    Returns the original path if the PDF is small enough already."""
    try:
        with pikepdf.open(source) as pdf:
            n_pages = len(pdf.pages)
            if n_pages <= first_n + 1:
                return source

            trimmed = pikepdf.Pdf.new()
            # First N pages
            for i in range(min(first_n, n_pages)):
                trimmed.pages.append(pdf.pages[i])
            # Last page
            trimmed.pages.append(pdf.pages[-1])

            suffix = source.stem[:20]  # keep part of original name
            fd, tmp_path = tempfile.mkstemp(
                suffix=".pdf",
                prefix=f"trim_{suffix}_",
                dir=tmp_dir,
            )
            os.close(fd)
            trimmed.save(tmp_path)
            return Path(tmp_path)
    except Exception as e:
        print(f"  Warning: could not trim {source.name}: {e}")
        return source


# ---------------------------------------------------------------------------
# File upload (concurrent)
# ---------------------------------------------------------------------------

async def upload_file(
    async_client,
    pdf_path: Path,
    semaphore: asyncio.Semaphore,
    progress: dict,
    display_name: str,
) -> tuple[str, object | None]:
    """Upload a PDF and return (display_name, uploaded_file_ref)."""
    async with semaphore:
        try:
            uploaded = await async_client.files.upload(file=pdf_path)
            progress["done"] += 1
            print(f"  [{progress['done']}/{progress['total']}] Uploaded: {display_name}")
            return display_name, uploaded
        except Exception as e:
            progress["done"] += 1
            print(f"  [{progress['done']}/{progress['total']}] FAILED: {display_name}: {e}")
            return display_name, None


async def upload_all_files(
    client: genai.Client,
    files: list[tuple[str, Path]],  # (display_name, path) pairs
) -> list[tuple[str, object]]:
    """Upload all files concurrently. Returns (display_name, uploaded_ref) pairs."""
    semaphore = asyncio.Semaphore(10)
    progress = {"done": 0, "total": len(files)}

    tasks = [
        upload_file(client.aio, path, semaphore, progress, name)
        for name, path in files
    ]

    results = await asyncio.gather(*tasks)
    return [(name, ref) for name, ref in results if ref is not None]


# ---------------------------------------------------------------------------
# Cleanup uploaded files (concurrent)
# ---------------------------------------------------------------------------

async def cleanup_file(async_client, ref, semaphore):
    async with semaphore:
        try:
            await async_client.files.delete(name=ref.name)
        except Exception:
            pass


async def cleanup_all_files(client: genai.Client, refs: list):
    semaphore = asyncio.Semaphore(10)
    tasks = [cleanup_file(client.aio, ref, semaphore) for ref in refs]
    await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Main matching call
# ---------------------------------------------------------------------------

def extract_and_match(
    client: genai.Client,
    source_uploaded,
    candidate_uploads: list[tuple[str, object]],
) -> list[FileMatch]:
    """Single Gemini call: source PDF + all candidate PDFs -> matches."""

    # Build contents: source PDF, then each candidate PDF labeled with filename
    contents = [source_uploaded]

    for filename, uploaded_ref in candidate_uploads:
        contents.append(f"\n--- CANDIDATE FILE: {filename} ---")
        contents.append(uploaded_ref)

    prompt = """\

YOUR TASK:
1. Read the ANA-ZAR source PDF (the first PDF above).
2. Extract every "(Dokument Nr. XXXX)" or "(Dokument Nr. XXXX y)" reference,
   where XXXX is a 4-5 digit number and y is an optional lowercase letter suffix.
3. For each reference, match it to the BEST fitting candidate PDF from the files
   above, using the citation context (court name, Aktenzeichen, date, description).

MATCHING RULES:
- Use court name, Aktenzeichen/case number, date, and document description
- Files already prefixed with a Dokumentnummer (e.g. "4224a_...") are already
  renamed — still include them with their correct dokument_nr + suffix
- Non-court documents (EUAA reports, DAV Stellungnahmen, EU council documents,
  ministry letters, brochures, press releases) should be matched by topic
- Each candidate PDF should be matched to AT MOST one Dokument Nr.
- If no candidate matches a reference, use "" for filename
- Be thorough: extract ALL Dokument Nr. references from the source PDF

OUTPUT:
For each reference return:
- dokument_nr: the number (e.g. "4224")
- suffix: the letter suffix if present (e.g. "b"), or "" if none
- filename: the exact candidate filename that matches, or "" if no match
"""
    contents.append(prompt)

    print("Matching references to candidate PDFs via Gemini...")
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=1.0,
            max_output_tokens=65536,
            response_mime_type="application/json",
            response_schema=MatchingResult,
        ),
    )

    if response.candidates and response.candidates[0].finish_reason.name == "MAX_TOKENS":
        print("WARNING: Response was truncated. Some references may be missing.")
        text = response.text.rstrip()
        last_brace = text.rfind("}")
        if last_brace != -1:
            text = text[:last_brace + 1] + "]}"
            try:
                result = MatchingResult.model_validate_json(text)
                return result.matches
            except Exception:
                pass
        print("ERROR: Could not parse truncated response.", file=sys.stderr)
        return []

    result = MatchingResult.model_validate_json(response.text)
    return result.matches


# ---------------------------------------------------------------------------
# Rename logic
# ---------------------------------------------------------------------------

def execute_renames(
    matches: list[FileMatch],
    folder: Path,
    separator: str,
    apply: bool,
) -> int:
    errors = 0
    available_files = {p.name: p for p in folder.glob("*.pdf")}
    already_assigned: set[str] = set()

    for m in matches:
        doc_id = f"{m.dokument_nr}{m.suffix}"

        if not m.filename:
            print(f"[FEHLT]    Dokument Nr. {doc_id}: keine passende Datei")
            errors += 1
            continue

        if m.filename not in available_files:
            print(f"[FEHLT]    Dokument Nr. {doc_id}: Datei nicht gefunden: {m.filename}")
            errors += 1
            continue

        if m.filename in already_assigned:
            print(f"[DOPPELT]  Dokument Nr. {doc_id}: {m.filename} bereits zugeordnet")
            errors += 1
            continue
        already_assigned.add(m.filename)

        path = available_files[m.filename]

        # Check if already renamed with correct prefix
        if path.name.startswith(f"{doc_id}{separator}"):
            print(f"[OK]       Bereits umbenannt: {path.name}")
            continue

        dst = path.with_name(f"{doc_id}{separator}{path.name}")
        if dst.exists():
            print(f"[KONFLIKT] Ziel existiert bereits: {dst.name}")
            errors += 1
            continue

        if apply:
            path.rename(dst)
            print(f"[RENAMED]  {path.name} -> {dst.name}")
        else:
            print(f"[DRY-RUN]  {path.name} -> {dst.name}")

    # Report unmatched files
    matched_filenames = {m.filename for m in matches if m.filename}
    unmatched = [
        name for name in sorted(available_files)
        if name not in matched_filenames
    ]
    if unmatched:
        print(f"\n--- Unmatched candidate files ({len(unmatched)}) ---")
        for name in unmatched:
            print(f"  {name}")

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_candidate_files(folder: Path, source_pdf: Path) -> list[Path]:
    out = []
    for p in sorted(folder.glob("*.pdf")):
        if p.resolve() == source_pdf.resolve():
            continue
        out.append(p)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reads an ANA-ZAR PDF, extracts '(Dokument Nr. ...)' references via Gemini API, "
            "matches them to candidate PDFs, and renames the files."
        )
    )
    parser.add_argument(
        "--source-pdf", required=True,
        help="Path to the ANA-ZAR source PDF with document references",
    )
    parser.add_argument(
        "--folder", default=".",
        help="Folder with candidate PDF files to rename (default: current dir)",
    )
    parser.add_argument(
        "--separator", default="_",
        help="Separator between document number and original filename (default: '_')",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually rename files (without this flag: dry-run only)",
    )
    parser.add_argument(
        "--pages", type=int, default=3,
        help="Number of first pages to include from each candidate PDF (default: 3)",
    )

    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)

    folder = Path(args.folder).resolve()
    source_pdf = Path(args.source_pdf).resolve()

    if not source_pdf.exists():
        print(f"Error: source PDF not found: {source_pdf}", file=sys.stderr)
        return 2

    if not folder.is_dir():
        print(f"Error: folder not found: {folder}", file=sys.stderr)
        return 2

    # Collect candidate files
    candidate_files = list_candidate_files(folder, source_pdf)
    if not candidate_files:
        print("No candidate PDF files found in folder.")
        return 1

    print(f"Found {len(candidate_files)} candidate PDF files.\n")

    # Trim candidate PDFs
    print("Trimming candidate PDFs (first {} pages + last page)...".format(args.pages))
    tmp_dir = tempfile.mkdtemp(prefix="dokrenamer_")
    trimmed_files: list[tuple[str, Path]] = []  # (original_filename, trimmed_path)
    temp_files: list[Path] = []

    for p in candidate_files:
        trimmed = trim_pdf(p, first_n=args.pages, tmp_dir=Path(tmp_dir))
        trimmed_files.append((p.name, trimmed))
        if trimmed != p:
            temp_files.append(trimmed)

    print(f"Trimmed {len(temp_files)} PDFs, {len(candidate_files) - len(temp_files)} used as-is.\n")

    # Upload source PDF + all trimmed candidates
    print("=" * 60)
    print("Phase 1: Uploading PDFs to Gemini")
    print("=" * 60)

    print(f"Uploading source PDF: {source_pdf.name}")
    source_uploaded = client.files.upload(file=source_pdf)

    print(f"Uploading {len(trimmed_files)} candidate PDFs...")
    candidate_uploads = asyncio.run(upload_all_files(client, trimmed_files))

    uploaded_refs = [source_uploaded] + [ref for _, ref in candidate_uploads]
    print(f"\nUploaded {len(candidate_uploads)}/{len(trimmed_files)} candidates successfully.\n")

    # Match
    print("=" * 60)
    print("Phase 2: Matching references to candidates")
    print("=" * 60)
    matches = extract_and_match(client, source_uploaded, candidate_uploads)

    # Cleanup uploaded files
    print("\nCleaning up uploaded files...")
    asyncio.run(cleanup_all_files(client, uploaded_refs))

    # Cleanup temp files
    for tmp in temp_files:
        try:
            tmp.unlink()
        except Exception:
            pass
    try:
        Path(tmp_dir).rmdir()
    except Exception:
        pass

    if not matches:
        print("No document references found.")
        return 1

    # Show results
    matched_count = sum(1 for m in matches if m.filename)
    unmatched_count = sum(1 for m in matches if not m.filename)
    print(f"\nFound {len(matches)} references: {matched_count} matched, {unmatched_count} unmatched\n")

    for m in matches:
        doc_id = f"{m.dokument_nr}{m.suffix}"
        if m.filename:
            print(f"  Nr. {doc_id} -> {m.filename}")
        else:
            print(f"  Nr. {doc_id} -> [no match]")

    # Rename
    print("\n" + "=" * 60)
    print(f"Phase 3: Renaming ({'APPLY' if args.apply else 'DRY-RUN'})")
    print("=" * 60)
    errors = execute_renames(matches, folder, args.separator, args.apply)

    print("\n" + "-" * 40)
    print(f"References: {len(matches)}")
    print(f"Candidates: {len(candidate_files)}")
    print(f"Errors/Warnings: {errors}")

    return 0 if errors == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
