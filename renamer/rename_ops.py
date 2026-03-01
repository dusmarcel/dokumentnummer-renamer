from .models import MatchResult
from .naming import build_target_filename


def rename_files(matches: list[MatchResult], separator: str, apply: bool) -> int:
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

    return errors
