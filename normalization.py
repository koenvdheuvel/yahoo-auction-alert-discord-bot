"""Versioned title normalization shared by live filtering and saved-data replay."""
import unicodedata


NORMALIZATION_VERSION = 1
MAX_TITLE_LENGTH = 10_000
DEFAULT_OPTIONS = {
    "nfkc": True,
    "casefold": True,
    "collapse_whitespace": True,
    "kana_fold": False,
}


def validate_options(options=None):
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("normalization must be an object")
    if set(options) - set(DEFAULT_OPTIONS):
        raise ValueError("Unknown normalization option")
    result = dict(DEFAULT_OPTIONS)
    for name, value in options.items():
        if type(value) is not bool:
            raise ValueError(f"normalization.{name} must be a boolean")
        result[name] = value
    return result


def _hiragana(text):
    extra = {"ヷ": "わ\u3099", "ヸ": "ゐ\u3099", "ヹ": "ゑ\u3099", "ヺ": "を\u3099",
             "ヽ": "ゝ", "ヾ": "ゞ"}
    return "".join(chr(ord(character) - 0x60) if "ァ" <= character <= "ヶ"
                   else extra.get(character, character) for character in text)


def normalize_title(text, options=None):
    """Return a normalized copy; punctuation, accents and original text survive.

    NFKC changes compatibility forms such as full-width Latin letters and
    half-width kana. Kana equivalence is opt-in; it preserves voicing, small
    kana and prolonged-sound marks rather than guessing pronunciation.
    """
    if not isinstance(text, str):
        raise ValueError("Title must be text")
    if len(text) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title exceeds {MAX_TITLE_LENGTH} characters")
    options = validate_options(options)
    result = unicodedata.normalize("NFKC", text) if options["nfkc"] else text
    if options["casefold"]:
        result = result.casefold()
    if options["kana_fold"]:
        result = _hiragana(result)
    if options["collapse_whitespace"]:
        result = " ".join(result.split())
    if len(result) > MAX_TITLE_LENGTH:
        raise ValueError("Normalized title exceeds the character limit")
    return result
