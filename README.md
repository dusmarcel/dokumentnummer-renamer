# Dokumentnummer Renamer

Python-Skript zum automatischen Umbenennen von PDF-Dateien anhand von Dokumentnummern aus einer ANA-ZAR-PDF.

## Funktionen

- Extrahiert `(Dokument Nr. XXXX)` aus einer Quell-PDF.
- Übernimmt optionale Buchstaben-Suffixe aus dem Heft (z. B. `4224a`, `4224b`) in den Dateipräfix.
- Matched Zitate gegen Dateinamen und PDF-Inhalte.
- Erkennt zusätzlich reine numerische Referenzen (z. B. `33689`) für numerische Dateinamen.
- Optional OCR-Fallback für gescannte Bild-PDFs (`tesseract` + `pdftoppm`).
- Optional dauerhaft durchsuchbare PDFs erzeugen (`ocrmypdf`).
- Gibt bei fehlenden oder mehrdeutigen Treffern Meldungen aus und läuft weiter.

## Voraussetzungen

- Python 3.10+
- `pdftotext` (aus `poppler-utils`)
- Optional:
  - `tesseract` + `pdftoppm` für OCR-Fallback
  - `ocrmypdf` für dauerhaft durchsuchbare PDFs

## Installation & Abhängigkeitsprüfung

Nur prüfen:

```bash
python3 rename_by_dokumentnummer.py --check-deps
```

Pflichtabhängigkeiten installieren (via erkanntem Paketmanager):

```bash
python3 rename_by_dokumentnummer.py --install-deps
```

Pflicht + optionale OCR-Abhängigkeiten installieren:

```bash
python3 rename_by_dokumentnummer.py --install-deps --with-optional-deps
```

Hinweise:
- Unterstützte Paketmanager: `apt-get`, `dnf`, `pacman`, `zypper`, `brew`.
- Arch Linux: `ocrmypdf` wird bei `--with-optional-deps` über AUR-Helper (`yay` oder `paru`) installiert, falls vorhanden.
- Je nach System sind `sudo`-Rechte erforderlich.

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
- Beispiel: `33689.pdf` kann bei einem Heft-Eintrag wie `OVG Lüneburg, B. v. 09.10.2025 - 9 LA 115/25 (Dokument Nr. 4227)` zu `4227_OVG_Lueneburg_B_v_09_10_2025_9_LA_115_25.pdf` werden.

## Lizenz

Dieses Projekt ist dual lizenziert unter:

- MIT (`LICENSE_MIT`)
- Apache License 2.0 (`LICENSE_APACHE`)

Du kannst die Lizenz wählen, die besser zu deinem Anwendungsfall passt.
