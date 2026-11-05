import functools
import html
import re
import unicodedata

# NFKD leaves the ligatures alone (no compatibility decomposition), so "Courtabœuf" would
# keep a non-ASCII letter and never match "Courtaboeuf". Spell them out first.
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})


@functools.lru_cache(maxsize=4096)
def normalize_text(text: str) -> str:
    """NFKD accent-fold, ligatures spelled out, lowercase, no punctuation, single spaces.

    Memoized: a posting's title, company and place go through here several times per run
    (fingerprint, dedup blocks, save, scoring), and the cache key is the string itself."""
    text = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|table|section)\b[^>]*>", re.I)


def html_to_text(markup: str | None) -> str:
    """Plain text from an HTML fragment: tags dropped, block tags become line breaks,
    entities decoded (twice: Greenhouse ships its `content` with the markup itself
    entity-encoded). Never executed, only stripped."""
    if not markup:
        return ""
    text = html.unescape(str(markup))
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line).strip()
