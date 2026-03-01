import os
import shutil
import subprocess
import sys

from .models import DependencyStatus

MIN_PYTHON = (3, 10)


def check_python_version() -> bool:
    return sys.version_info >= MIN_PYTHON


def collect_dependency_status() -> list[DependencyStatus]:
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


def print_dependency_status(statuses: list[DependencyStatus]) -> None:
    print("Abhängigkeitsprüfung:")
    for dep in statuses:
        kind = "PFLICHT" if dep.required else "OPTIONAL"
        state = "OK" if dep.found_path else "FEHLT"
        path = dep.found_path if dep.found_path else "-"
        print(f"- [{state}] {dep.tool:<11} ({kind}) | {dep.note} | {path}")


def required_dependencies_ok(statuses: list[DependencyStatus]) -> bool:
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


def build_install_steps(manager: str, include_optional: bool) -> list[list[str]]:
    needs_elevation = manager in {"apt-get", "dnf", "pacman", "zypper"}
    if needs_elevation and hasattr(os, "geteuid") and os.geteuid() != 0:
        if shutil.which("sudo") is None:
            print("Hinweis: 'sudo' nicht gefunden. Installation könnte wegen fehlender Rechte fehlschlagen.")
            prefix: list[str] = []
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
