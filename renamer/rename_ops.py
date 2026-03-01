from pathlib import Path

from .models import MatchResult, RenameSummary
from .naming import build_target_filename
from .text_utils import normalize_text


def filename_starts_with_doc_id(path: Path, doc_id: str) -> bool:
    normalized_stem = normalize_text(path.stem)
    normalized_doc_id = normalize_text(doc_id)
    return normalized_stem == normalized_doc_id or normalized_stem.startswith(f"{normalized_doc_id} ")


def filename_already_covers_target(src: Path, target_name: str, doc_id: str) -> bool:
    if not filename_starts_with_doc_id(src, doc_id):
        return False

    src_tokens = set(normalize_text(src.stem).split())
    target_tokens = set(normalize_text(Path(target_name).stem).split())
    return target_tokens.issubset(src_tokens)


def rename_unused_files(
    unused_paths: list[Path],
    apply: bool,
    mark_unused: bool,
    unused_prefix: str,
) -> int:
    errors = 0
    for path in unused_paths:
        print(f"[UNBENUTZT] {path.name}")
        if not mark_unused:
            continue

        if path.name.startswith(f"{unused_prefix}_"):
            continue

        dst = path.with_name(f"{unused_prefix}_{path.name}")
        if dst.exists():
            print(f"[KONFLIKT] Unbenutzte Datei konnte nicht markiert werden: {dst.name}")
            errors += 1
            continue

        if apply:
            try:
                path.rename(dst)
            except OSError as exc:
                print(f"[FEHLER] Unbenutzte Datei konnte nicht markiert werden: {path.name} | {exc}")
                errors += 1
                continue
            print(f"[MARKIERT] {path.name} -> {dst.name}")
        else:
            print(f"[DRY-RUN] {path.name} -> {dst.name}")
    return errors


def rename_files(
    matches: list[MatchResult],
    candidate_files: list[Path],
    separator: str,
    apply: bool,
    mark_unused: bool = False,
    unused_prefix: str = "UNUSED",
) -> RenameSummary:
    errors = 0
    already_assigned: dict[object, str] = {}

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
            for path in result.matches:
                print(f"         - {path.name}")
            errors += 1
            continue

        src = result.matches[0]
        if src in already_assigned:
            if already_assigned[src] != doc_id:
                print(
                    f"[DOPPELT] Datei bereits Dokument Nr. {already_assigned[src]} zugeordnet: "
                    f"{src.name} (neu: {doc_id})"
                )
                errors += 1
                continue
            print(f"[OK] Bereits derselben Dokumentnummer zugeordnet: {src.name}")
            continue
        already_assigned[src] = doc_id

        target_name = build_target_filename(ref, src, separator)

        if filename_already_covers_target(src, target_name, doc_id):
            print(f"[OK] Bereits passend nummeriert: {src.name}")
            continue

        if src.name == target_name:
            print(f"[OK] Bereits umbenannt: {src.name}")
            continue

        dst = src.with_name(target_name)
        if dst.exists():
            print(
                f"[KONFLIKT] Ziel existiert bereits für Dokument Nr. {doc_id}: {dst.name}"
            )
            errors += 1
            continue

        if apply:
            try:
                src.rename(dst)
            except PermissionError as exc:
                print(
                    f"[GESPERRT] Dokument Nr. {doc_id}: {src.name} konnte nicht umbenannt werden "
                    f"(Datei vermutlich in Windows geoeffnet/gesperrt) | {exc}"
                )
                errors += 1
                continue
            except OSError as exc:
                print(
                    f"[FEHLER] Dokument Nr. {doc_id}: {src.name} konnte nicht umbenannt werden | {exc}"
                )
                errors += 1
                continue
            print(f"[UMBENANNT] {src.name} -> {dst.name}")
        else:
            print(f"[DRY-RUN] {src.name} -> {dst.name}")

    assigned_paths = set(already_assigned.keys())
    unused_paths = sorted(path for path in candidate_files if path not in assigned_paths)
    errors += rename_unused_files(
        unused_paths,
        apply=apply,
        mark_unused=mark_unused,
        unused_prefix=unused_prefix,
    )
    return RenameSummary(
        errors=errors,
        assigned_paths=assigned_paths,
        unused_paths=unused_paths,
    )
