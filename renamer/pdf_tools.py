import shutil
import subprocess
import tempfile
import re
from pathlib import Path

from .models import CandidateDoc
from .text_utils import normalize_text, tokenize


HEADER_SIGNAL_RE = re.compile(
    r"\b(vg|ovg|vgh|bverwg|bverfg|eugh|verwaltungsgericht|beschluss|urteil)\b",
    re.IGNORECASE,
)
AKTENZEICHEN_SIGNAL_RE = re.compile(
    r"\b[A-Z]?\s*\d{1,3}\s*[A-Za-z]{0,4}\s*\d{1,5}\s*[/.-]\s*\d{2,4}\b"
)


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

        chunks: list[str] = []
        for img in pages:
            ocr_cmd = ["tesseract", str(img), "stdout", "-l", ocr_lang, "--psm", "6"]
            proc = subprocess.run(ocr_cmd, check=False, capture_output=True)
            if proc.returncode != 0:
                continue
            chunks.append(proc.stdout.decode("utf-8", errors="ignore"))
        return "\n".join(chunks)


def text_has_structured_header(text: str) -> bool:
    head = text[:1200]
    return bool(HEADER_SIGNAL_RE.search(head) and AKTENZEICHEN_SIGNAL_RE.search(head))


def maybe_enrich_with_header_ocr(
    pdf_path: Path,
    text: str,
    ocr_dpi: int,
    ocr_lang: str,
) -> str:
    if text_has_structured_header(text):
        return text
    if shutil.which("tesseract") is None or shutil.which("pdftoppm") is None:
        return text

    try:
        ocr_text = run_ocr_text(pdf_path, ocr_pages=1, ocr_dpi=ocr_dpi, ocr_lang=ocr_lang)
    except RuntimeError:
        return text

    if not text_has_structured_header(ocr_text):
        return text
    if normalize_text(ocr_text) in normalize_text(text):
        return text
    return f"{ocr_text}\n{text}".strip()


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
    files: list[Path],
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
    for path in files:
        name_tokens = set(tokenize(path.stem))
        content_tokens: set[str] = set()
        norm_content = ""
        content_source = path

        if make_searchable:
            try:
                content_source = build_searchable_pdf(
                    path,
                    out_dir=searchable_dir,
                    ocr_lang=ocr_lang,
                    force=searchable_force,
                )
            except RuntimeError:
                content_source = path

        if analyze_content:
            try:
                text = run_pdftotext(content_source)
            except RuntimeError:
                text = ""

            text = maybe_enrich_with_header_ocr(
                content_source,
                text,
                ocr_dpi=ocr_dpi,
                ocr_lang=ocr_lang,
            )

            if use_ocr and len(normalize_text(text)) < 80:
                try:
                    ocr_text = run_ocr_text(
                        content_source,
                        ocr_pages=ocr_pages,
                        ocr_dpi=ocr_dpi,
                        ocr_lang=ocr_lang,
                    )
                    if len(normalize_text(ocr_text)) > len(normalize_text(text)):
                        text = ocr_text
                except RuntimeError:
                    pass

            norm_content = normalize_text(text)
            content_tokens = set(norm_content.split()) if norm_content else set()

        index[path] = CandidateDoc(
            path=path,
            name_tokens=name_tokens,
            content_tokens=content_tokens,
            norm_content=norm_content,
        )
    return index
