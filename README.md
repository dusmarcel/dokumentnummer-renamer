# Dokumentnummer Renamer

Python-Skript zum automatischen Umbenennen von PDF-Dateien anhand von Dokumentnummern aus einer ANA-ZAR-PDF.

## Funktionen

- Extrahiert `(Dokument Nr. XXXX)` aus einer Quell-PDF.
- Matched Zitate gegen Dateinamen und PDF-Inhalte.
- Optional OCR-Fallback für gescannte Bild-PDFs (`tesseract` + `pdftoppm`).
- Optional dauerhaft durchsuchbare PDFs erzeugen (`ocrmypdf`).
- Gibt bei fehlenden oder mehrdeutigen Treffern Meldungen aus und läuft weiter.

## Voraussetzungen

- Python 3.10+
- `pdftotext` (aus `poppler-utils`)
- Optional:
  - `tesseract` für OCR-Fallback
  - `ocrmypdf` für dauerhaft durchsuchbare PDFs

## Nutzung

Dry-Run:

```bash
python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder .
```

Umbenennung anwenden:

```bash
python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder . --apply
```

Mit OCR-Fallback:

```bash
python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder . --ocr
```

Durchsuchbare PDFs erzeugen:

```bash
python3 rename_by_dokumentnummer.py --source-pdf ANA-ZAR_1_26_Online.pdf --folder . --make-searchable
```

## Hinweise

- Ohne `--apply` wird nichts umbenannt.
- Für große Ordner kann OCR länger dauern.
- Das Skript ist defensiv: bei unklaren Treffern wird nicht automatisch umbenannt.

## Lizenz

Dieses Projekt ist dual lizenziert unter:

- MIT (`LICENSE-MIT`)
- Apache License 2.0 (`LICENSE-APACHE`)

Du kannst die Lizenz wählen, die besser zu deinem Anwendungsfall passt.
