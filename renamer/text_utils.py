import re
import unicodedata


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def transliterate_german(text: str) -> str:
    replacements = {
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def split_filename_words(text: str) -> list[str]:
    cleaned = transliterate_german(text)
    return [part for part in re.split(r"[^A-Za-z0-9]+", cleaned) if part]


def format_filename_word(word: str) -> str:
    if word.isdigit():
        return word
    if word.isupper():
        return word
    if any(ch.isupper() for ch in word[1:]):
        return word
    return word[:1].upper() + word[1:].lower()
