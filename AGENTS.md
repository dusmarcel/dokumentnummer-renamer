# Repository Guidelines

## Project Structure & Module Organization
- `rename_by_dokumentnummer.py`: main CLI script with parsing, matching logic, OCR helpers, and rename execution.
- `README.md`: end-user usage examples and dependency notes.
- `.gitignore`: local ignore rules.

This repository is intentionally small and script-centric. Keep new logic in focused functions and avoid spreading core behavior across many files unless complexity clearly warrants it.

## Build, Test, and Development Commands
- `python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder .`
  - Dry-run (default): prints planned renames without changing files.
- `python3 rename_by_dokumentnummer.py --check-deps`
  - Checks required/optional dependencies and exits.
- `python3 rename_by_dokumentnummer.py --install-deps --with-optional-deps`
  - Installs required plus optional OCR dependencies (if supported package manager is found).
- `python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder . --apply`
  - Applies renames.
- `python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder . --ocr`
  - Enables OCR fallback (`tesseract` + `pdftoppm`).
- `python3 rename_by_dokumentnummer.py --help`
  - Lists all CLI options.

Dependencies: Python 3.10+, `pdftotext` (required), optional `tesseract`, `pdftoppm`, `ocrmypdf`.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and clear, small functions.
- Use `snake_case` for functions/variables, `UPPER_CASE` for constants, and `PascalCase` for dataclasses (`DocumentRef`, `MatchResult`, `CandidateDoc`).
- Prefer type hints for new/changed functions.
- Keep CLI output explicit and defensive (warn instead of failing entire batch when possible).

## Testing Guidelines
- No automated test suite exists yet; validate changes with representative PDFs.
- Always run one dry-run before any `--apply` execution.
- Verify edge cases: ambiguous matches, missing matches, scanned PDFs with `--ocr`, and existing target-name conflicts.

## Commit & Pull Request Guidelines
- Current history uses concise, imperative commit subjects (example: `Initial commit: document-number PDF renamer`).
- Recommended format: `<type>: <short summary>` (e.g., `fix: tighten date-token filtering`).
- PRs should include:
  - purpose and behavior change summary,
  - exact command(s) used for validation,
  - sample before/after rename output for non-trivial matching changes.

## Safety & Operational Notes
- Default to dry-run; use `--apply` only after reviewing output.
- Do not rename source PDFs manually during a run.
- Treat OCR/searchable-PDF generation as optional performance tradeoffs for difficult inputs.
