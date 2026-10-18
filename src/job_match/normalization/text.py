import re
import unicodedata

# NFKD leaves the ligatures alone (no compatibility decomposition), so "Courtabœuf" would
# keep a non-ASCII letter and never match "Courtaboeuf". Spell them out first.
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})


def normalize_text(text: str) -> str:
    """NFKD accent-fold, ligatures spelled out, lowercase, no punctuation, single spaces."""
    text = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
