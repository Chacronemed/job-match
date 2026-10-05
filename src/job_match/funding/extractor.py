"""Rule-based FR/EN funding extraction. Pure functions, no I/O, no LLM.

Every extracted field carries the sentence it came from (``evidence``). Unknown is ``None``:
no amount without an explicit number + unit, no investors without an explicit cue, no
hiring signal without an explicit phrase. See ADR 0003.
"""
import re
from dataclasses import dataclass, field

from job_match.normalization.company import normalize_company
from job_match.normalization.numbers import WORD_NUMBERS
from job_match.normalization.text import normalize_text

MAX_EVIDENCE_CHARS = 300
MIN_AMOUNT = 1e4  # below this a "levée" is not a funding round (or the unit is missing)
MAX_AMOUNT = 1e11


@dataclass(frozen=True, slots=True)
class FundingExtraction:
    is_funding: bool
    company: str | None = None
    amount: float | None = None  # base units: 10 M€ -> 10_000_000.0
    currency: str | None = None  # EUR | USD | GBP
    round: str | None = None  # pre-seed | seed | series a..h | bridge
    investors: tuple[str, ...] | None = None
    hiring: str | None = None  # the matched phrase, e.g. "recruter une trentaine de personnes"
    location: str | None = None
    country: str | None = None  # explicit only: "startup suisse", "London-based"
    evidence: dict[str, str] = field(default_factory=dict)  # field -> sentence


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_NBSP_RE = re.compile(r"[  ]")
_BULLET_RE = re.compile(r"^\s*[-•*–—]\s*")
# "M. Dupont", "Inc.", "etc." must not end a sentence
_ABBR_RE = re.compile(r"\b(M|Mme|Mlle|Dr|St|Inc|Ltd|Co|Corp|etc|env|cf|vs|n°)\.", re.IGNORECASE)
# "... en mai 2026.L'entreprise" (missing space after the period) is also a boundary
_SENT_SPLIT_RE = re.compile(
    r"(?<=[.!?…])\s+(?=[«\"“(A-ZÀ-Ý0-9])|(?<=[a-zà-ÿ0-9][.!?…])(?=[«\"“A-ZÀ-Ý])"
)
_DOT_SENTINEL = "\x00"


def split_sentences(text: str) -> list[str]:
    """Split FR/EN prose into sentences. Bullets and blank lines are boundaries."""
    out: list[str] = []
    for line in _NBSP_RE.sub(" ", text or "").split("\n"):
        line = _BULLET_RE.sub("", line).strip()
        if not line:
            continue
        protected = _ABBR_RE.sub(lambda m: m.group(1) + _DOT_SENTINEL, line)
        for part in _SENT_SPLIT_RE.split(protected):
            part = part.replace(_DOT_SENTINEL, ".").strip()
            if part:
                out.append(re.sub(r"\s+", " ", part))
    return out


# ---------------------------------------------------------------------------
# Funding signals
# ---------------------------------------------------------------------------

# Strong noun phrases: sufficient on their own ("Acme annonce une levée de fonds")
_STRONG_RE = re.compile(
    r"lev[ée]e de fonds|l[eè]ve(?:nt)? des fonds|lever des fonds|tour de table"
    r"|tour de financement|tour d['’]amor[cç]age|lev[ée]e d['’]amor[cç]age|pr[ée]-?\s?amor[cç]age"
    r"|funding round|seed round|series [a-h] round|raises funding|secures funding"
    r"|financing round|pre-?seed (?:funding|round)|in (?:new )?funding\b",
    re.IGNORECASE,
)

# Verbs: need an accepted amount in the same sentence ("Acme lève 10 M€")
_VERB_RE = re.compile(
    r"\b(?:l[eè]ve(?:nt)?|a lev[ée]|ont lev[ée]|vient de lever|viennent de lever"
    r"|boucle(?:nt)?|a boucl[ée]|ont boucl[ée]|r[ée]alise une lev[ée]e|annonce une lev[ée]e"
    r"|cl[oô]ture|s[ée]curise|d[ée]croche|obtient un financement"
    r"|raises|raised|has raised|have raised|secures|secured|closes|closed|lands|landed"
    r"|bags|nabs)\b",
    re.IGNORECASE,
)

# Non-funding uses of the verbs, checked right after the verb match
_VERB_EXCL_RE = re.compile(
    r"^\s+(?:le voile|un coin du voile|le pied|les yeux|la main|des doutes|le myst[èe]re"
    r"|l['’]ancre|une arm[ée]e|the bar|concerns?|questions?|awareness|eyebrows|doubts?"
    r"|alarm|prices?|its prices|the stakes)\b",
    re.IGNORECASE,
)

# Sentence-level guards: a sentence matching these is never the funding sentence
_MONTHS = (
    r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre"
    r"|d[ée]cembre|january|february|march|april|may|june|july|august|september|october"
    r"|november|december)"
)
_PAST_RE = re.compile(
    r"avait (?:d[ée]j[àa] )?(?:lev[ée]|boucl[ée])|apr[èe]s avoir lev[ée]|a d[ée]j[àa] lev[ée]"
    r"|d[ée]j[àa] lev[ée]|lors de (?:sa|son) (?:pr[ée]c[ée]dente?|derni[èe]re?)"
    r"|had raised|previously raised|after raising|having raised|in (?:a|its) previous round"
    # passé composé / past tense tied to an explicit past date: "a levé 40 M$ en mai 2026",
    # "raised $3M in March 2025", "depuis un tour de table ... en février dernier"
    r"|(?:a|ont) lev[ée][^.;]{0,80}\ben (?:" + _MONTHS + r"\s+)?(?:19|20)\d{2}\b"
    r"|raised[^.;]{0,80}\bin (?:" + _MONTHS + r"\s+)?(?:19|20)\d{2}\b"
    r"|en " + _MONTHS + r" derni[èe]re?|l['’]an dernier|l['’]ann[ée]e derni[èe]re|last year"
    r"|earlier this year|il y a \d+ (?:mois|ans)|\d+ (?:months|years) ago"
    r"|depuis (?:un|son|sa|le|la) (?:tour|lev[ée]e)|[ée]tait valoris[ée]e",
    re.IGNORECASE,
)
_VC_FUND_RE = re.compile(
    r"pour son (?:nouveau|premier|deuxi[èe]me|second|troisi[èe]me|quatri[èe]me) fonds"
    r"|nouveau fonds de|closing (?:final|interm[ée]diaire)|\bfund (?:I{1,3}|IV|VI?)\b"
    r"|closes [^.;]{0,40}\bfund\b|\bnew fund\b",
    re.IGNORECASE,
)

# Clause-level guard: amounts in the same clause are not funding amounts
_AMOUNT_GUARD_RE = re.compile(
    r"chiffre d['’]affaires|\brevenus?\b|\brevenue\b|\bARR\b|valoris|valued at|valuation"
    r"|b[ée]n[ée]fice|\bpertes?\b|rentabilit|subvention"
    r"|march[ée]s? (?:de|du|des|mondial|fran[cç]ais|europ[ée]en)"
    r"|\bmarket (?:size|worth|of|valued|estimated)|\bTAM\b"
    r"|total lev[ée]|au total|in total|to date|depuis sa cr[ée]ation|since (?:its )?inception"
    r"|cumul[ée]|[ée]conomies?|op[ée]ration de liquidit[ée]|\bsecondaire\b|\bsecondary\b"
    r"|\bdette\b|\bdebt\b|\bpr[êe]t\b|\bloan\b",
    re.IGNORECASE,
)
_CA_RE = re.compile(r"\bCA\b")  # case-sensitive: "CA" (chiffre d'affaires), not "ca"
_CLAUSE_SPLIT_RE = re.compile(r"[,;:()]|\s(?:et|and|dont)\s", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Amount + currency
# ---------------------------------------------------------------------------

_WORD_ALT = "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))
# "1 200 000" / "10.000" (3-digit groups) | "1,5" / "19.4" / "264" | "dix"
_NUM = (
    r"(?P<num>\d{1,3}(?:[ .]\d{3})+(?![.,]\d)|\d+(?:[.,]\d+)?|\b(?:" + _WORD_ALT + r")\b)"
)
_SCALE_WORDS = r"(?P<scale>milliards?|millions?|billions?|thousand|mille|mds?|md)"
_SCALE_SYM = r"(?P<scale>milliards?|millions?|billions?|thousand|mds?|md|mn|bn|k|m|b)"
_CUR_WORD = (
    r"(?P<curw>euros?|dollars?(?:\s+am[ée]ricains)?|livres?(?:\s+sterling)?|EUR|USD|GBP)\b"
)

# 1. "10 millions d'euros", "500 000 euros", "1,5 milliard d'euros", "20 millions de dollars"
_AMOUNT_WORD_RE = re.compile(
    _NUM + r"\s*(?:" + _SCALE_WORDS + r")?\s*(?:de\s+|d['’]\s*)?" + _CUR_WORD, re.IGNORECASE
)
# 2. "$5M", "€5m", "$50 million", "£2.5m", "$1.2 billion"
_AMOUNT_SYM_FIRST_RE = re.compile(
    r"(?P<sym>[€$£])\s?" + _NUM + r"\s?(?:" + _SCALE_SYM + r")?(?![\w.])", re.IGNORECASE
)
# 3. "10 M€", "10M€", "5 M$", "300 k€", "2 Md€", "500 000 €"
_AMOUNT_SYM_LAST_RE = re.compile(
    _NUM + r"\s?(?:" + _SCALE_SYM + r")?\s?(?P<sym>[€$£])", re.IGNORECASE
)
_PERCENT_AFTER_RE = re.compile(r"^\s?%")

_SCALE_FACTORS: dict[str, float] = {
    "k": 1e3, "mille": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
    "md": 1e9, "mds": 1e9, "milliard": 1e9, "milliards": 1e9,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9,
}
_CURRENCIES: dict[str, str] = {
    "€": "EUR", "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "$": "USD", "dollar": "USD", "dollars": "USD", "usd": "USD",
    "£": "GBP", "livre": "GBP", "livres": "GBP", "gbp": "GBP",
}


@dataclass(frozen=True, slots=True)
class _Amount:
    start: int
    end: int
    value: float
    currency: str


def _parse_number(raw: str) -> float | None:
    raw = raw.strip()
    word = WORD_NUMBERS.get(raw.lower())
    if word is not None:
        return float(word)
    if re.fullmatch(r"\d{1,3}(?:[ .]\d{3})+", raw):
        return float(re.sub(r"[ .]", "", raw))
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _currency_of(token: str) -> str | None:
    key = token.lower().split()[0] if token.strip() else ""
    key = re.sub(r"[^\w€$£]", "", key)
    return _CURRENCIES.get(key)


def _amount_candidates(sentence: str) -> list[_Amount]:
    """All plausible amounts in a sentence, with their spans. Guards are applied later."""
    found: list[_Amount] = []
    claimed: list[tuple[int, int]] = []
    for pattern in (_AMOUNT_WORD_RE, _AMOUNT_SYM_FIRST_RE, _AMOUNT_SYM_LAST_RE):
        for m in pattern.finditer(sentence):
            if any(m.start() < e and m.end() > s for s, e in claimed):
                continue
            if _PERCENT_AFTER_RE.match(sentence[m.end():]):
                continue
            number = _parse_number(m.group("num"))
            if number is None:
                continue
            scale = (m.group("scale") or "").lower()
            value = number * _SCALE_FACTORS.get(scale, 1.0)
            if not (MIN_AMOUNT <= value <= MAX_AMOUNT):
                continue
            cur_token = m.group("curw") if "curw" in m.groupdict() and m.group("curw") else None
            cur_token = cur_token or m.group("sym")
            currency = _currency_of(cur_token)
            if currency is None:
                continue
            claimed.append((m.start(), m.end()))
            found.append(_Amount(m.start(), m.end(), value, currency))
    return sorted(found, key=lambda a: a.start)


def _clause_spans(sentence: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _CLAUSE_SPLIT_RE.finditer(sentence):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(sentence)))
    return spans


def _clause_guarded(sentence: str, pos: int) -> bool:
    for s, e in _clause_spans(sentence):
        if s <= pos < e:
            clause = sentence[s:e]
            return bool(_AMOUNT_GUARD_RE.search(clause) or _CA_RE.search(clause))
    return False


def _accepted_amounts(sentence: str) -> list[_Amount]:
    return [a for a in _amount_candidates(sentence) if not _clause_guarded(sentence, a.start)]


# ---------------------------------------------------------------------------
# Funding sentence detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _FundingSentence:
    text: str
    anchor: int  # start of the verb / strong phrase (company is looked up before it)
    amounts: tuple[_Amount, ...]


def _is_guarded_sentence(sentence: str) -> bool:
    return bool(_PAST_RE.search(sentence) or _VC_FUND_RE.search(sentence))


def _verb_matches(sentence: str) -> list[re.Match]:
    return [
        m for m in _VERB_RE.finditer(sentence) if not _VERB_EXCL_RE.match(sentence[m.end():])
    ]


def _as_funding_sentence(sentence: str) -> _FundingSentence | None:
    if _is_guarded_sentence(sentence):
        return None
    verbs = _verb_matches(sentence)
    strong = _STRONG_RE.search(sentence)
    amounts = tuple(_accepted_amounts(sentence))
    if strong is None and not (verbs and amounts):
        return None
    anchor = verbs[0].start() if verbs else strong.start()  # type: ignore[union-attr]
    return _FundingSentence(sentence, anchor, amounts)


def _nearest_amount(fs: _FundingSentence) -> _Amount | None:
    if not fs.amounts:
        return None
    return min(fs.amounts, key=lambda a: abs(a.start - fs.anchor))


# ---------------------------------------------------------------------------
# Company name heuristic
# ---------------------------------------------------------------------------

_APPOSITIVE_RE = re.compile(r",[^,]{0,80},\s*$")
_TRAILING_FILLER_RE = re.compile(
    r"(?:\b(?:un|une|son|sa|ses|le|la|les|de|du|des|d['’]|l['’]|aujourd['’]hui|hier|ce matin"
    r"|ce (?:lundi|mardi|mercredi|jeudi|vendredi)|cette semaine|[ée]galement|ainsi|d[ée]sormais"
    r"|officiellement|annonce|annoncent|a annonc[ée]|ont annonc[ée]|vient de|viennent de"
    r"|r[ée]alise|a r[ée]alis[ée]|finalise|a finalis[ée]|just|today|has|have|officially"
    r"|announces|announced)|[,:;–—-])\s*$",
    re.IGNORECASE,
)
_NAME_TOKEN_RE = re.compile(r"^[A-ZÀ-Ý0-9][\w'’.&-]*$")
_DESCRIPTOR_TOKENS = frozenset({
    "la", "le", "l'", "l’", "les", "the", "a", "an", "french", "british", "german",
    "startup", "start-up", "société", "societe", "pépite", "pepite", "fintech", "healthtech",
    "scale-up", "scaleup", "licorne", "plateforme", "entreprise", "company", "platform",
    "startups", "jeune", "pousse",
})
_COMPANY_STOPLIST = frozenset({
    "french tech", "la french tech", "ia", "ai", "tech", "startup", "startups", "bpifrance",
    "europe", "france", "paris", "la startup", "la societe", "l entreprise", "elle", "il",
    "the company", "company", "it", "we",
})
_MAX_NAME_TOKENS = 5
_MAX_NAME_CHARS = 60


def _company_before(sentence: str, anchor: int) -> str | None:
    before = sentence[:anchor]
    changed = True
    while changed:
        changed = False
        new = _APPOSITIVE_RE.sub(",", before)
        if new != before:
            before, changed = new, True
        new = _TRAILING_FILLER_RE.sub("", before)
        if new != before:
            before, changed = new, True
    tokens = before.strip().split()
    run: list[str] = []
    for tok in reversed(tokens):
        if _NAME_TOKEN_RE.match(tok) and len(run) < _MAX_NAME_TOKENS:
            run.insert(0, tok)
        else:
            break
    while run and (run[0].lower() in _DESCRIPTOR_TOKENS or run[0].lower().endswith("-based")):
        run.pop(0)
    name = " ".join(run).strip(" ,.;:")
    if not name or len(name) > _MAX_NAME_CHARS:
        return None
    if normalize_company(name) in _COMPANY_STOPLIST or not normalize_company(name):
        return None
    return name


# ---------------------------------------------------------------------------
# Round
# ---------------------------------------------------------------------------

_ROUND_RE = re.compile(
    r"(?P<preseed>pr[ée]-?\s?seed|pr[ée]-?\s?amor[cç]age)"
    r"|(?P<seed>\bseed\b|\bamor[cç]age\b)"
    r"|(?P<series>\bs[ée]ries?\s+(?P<letter>[A-H])\b)"
    r"|(?P<bridge>\bbridge\b)",
    re.IGNORECASE,
)


def _round_in(sentence: str) -> str | None:
    m = _ROUND_RE.search(sentence)
    if m is None:
        return None
    if m.group("preseed"):
        return "pre-seed"
    if m.group("seed"):
        return "seed"
    if m.group("series"):
        return f"series {m.group('letter').lower()}"
    return "bridge"


# ---------------------------------------------------------------------------
# Investors
# ---------------------------------------------------------------------------

_INVESTOR_CUE_RE = re.compile(
    r"(?:co-?)?men[ée]e?s? par(?: les? fonds)?|(?:conduite?|dirig[ée]e?|emmen[ée]e?) par"
    r"|aupr[èe]s (?:de|d['’])|avec la participation (?:de|d['’])|avec le soutien (?:de|d['’])"
    r"|aux c[ôo]t[ée]s (?:de|d['’])"
    r"|(?:accompagn[ée]e?|soutenue?|financ[ée]e?) par|investisseurs?\s*:"
    r"|(?:co-?)?led by|with (?:the )?participation (?:from|of)|backed by|joined by|alongside"
    r"|investors including",
    re.IGNORECASE,
)
_INVESTOR_FROM_RE = re.compile(r"\bfrom\s+(?=[A-Z])")
_INVESTOR_TERMINATOR_RE = re.compile(
    r"[.;:)]|\s(?:pour|afin|dans|qui|dont|à l['’]occasion|en vue|to|for|which|who|in order"
    r"|that|afin)\b",
    re.IGNORECASE,
)
_INVESTOR_SPLIT_RE = re.compile(r",|;|\set\s|\sand\s|\sainsi que\s|\s&\s|/", re.IGNORECASE)
_INVESTOR_LEAD_RE = re.compile(
    r"^(?:le fonds|les fonds|la soci[ée]t[ée]|le groupe|le|la|les|l['’]|the fund|the firm|the"
    r"|ses|its|notamment|dont|including|de|d['’])\s+",
    re.IGNORECASE,
)
_INVESTOR_WHITELIST = frozenset({
    "business angels", "angel investors", "investisseurs historiques", "existing investors",
    "family offices", "historical investors", "ses investisseurs historiques",
})
_MAX_INVESTORS = 10
_MAX_SPAN = 200


def _investor_spans(sentence: str) -> list[str]:
    cues = list(_INVESTOR_CUE_RE.finditer(sentence))
    if _VERB_RE.search(sentence) and re.search(r"\braised?|\bsecure[sd]?\b", sentence, re.I):
        cues += list(_INVESTOR_FROM_RE.finditer(sentence))
    cues.sort(key=lambda m: m.start())
    spans: list[str] = []
    for i, cue in enumerate(cues):
        end = cues[i + 1].start() if i + 1 < len(cues) else len(sentence)
        chunk = sentence[cue.end():end][:_MAX_SPAN]
        term = _INVESTOR_TERMINATOR_RE.search(chunk)
        if term:
            chunk = chunk[: term.start()]
        spans.append(chunk)
    return spans


_INVESTOR_DESCRIPTOR_SPLIT_RE = re.compile(r"\bd['’]|\bde\s+|\bdu\s+", re.IGNORECASE)


def _clean_investor(token: str) -> str:
    token = re.sub(r"\([^)]*\)", "", token).strip(" .,;:«»\"“”")
    prev = None
    while prev != token:
        prev = token
        token = _INVESTOR_LEAD_RE.sub("", token).strip()
    # "branche de capital-innovation d'Épopée Gestion" -> "Épopée Gestion": a token that
    # starts lowercase is a descriptor; keep only the name after its last "de"/"d'".
    if token and token[0].islower() and token.lower() not in _INVESTOR_WHITELIST:
        tail = _INVESTOR_DESCRIPTOR_SPLIT_RE.split(token)[-1].strip()
        token = tail if tail and tail[0].isupper() else token
    return token


def _investors_in(sentence: str, company: str | None) -> tuple[str, ...] | None:
    company_n = normalize_company(company) if company else None
    out: list[str] = []
    for span in _investor_spans(sentence):
        for raw in _INVESTOR_SPLIT_RE.split(span):
            tok = _clean_investor(raw)
            if not (2 <= len(tok) <= 60):
                continue
            if _amount_candidates(tok):
                continue
            if tok.lower() not in _INVESTOR_WHITELIST and not re.search(r"[A-ZÀ-Ý]", tok):
                continue
            if company_n and normalize_company(tok) == company_n:
                continue
            if tok not in out:
                out.append(tok)
            if len(out) >= _MAX_INVESTORS:
                break
    return tuple(out) if out else None


# ---------------------------------------------------------------------------
# Hiring signal — a verb or an explicit plan is required, never a bare noun
# ---------------------------------------------------------------------------

_HIRING_PRESTRIP_RE = re.compile(
    r"(?:plateforme|cabinet|solution|logiciel|outil|startup|sp[ée]cialiste|agence|march[ée])"
    r"\s+(?:de|du)\s+recrutement|(?:recruiting|recruitment|hiring)\s+(?:platform|software|startup)",
    re.IGNORECASE,
)
_HIRING_NEGATIVE_RE = re.compile(
    r"licenci|layoffs?|suppression de postes|plan social|gel des (?:embauches|recrutements)",
    re.IGNORECASE,
)
_SIZE_WORDS = (
    r"(?:\d+|une (?:dizaine|vingtaine|trentaine|quarantaine|cinquantaine|centaine)"
    r"|plusieurs|des dizaines|des centaines)"
)
_PEOPLE = (
    r"(?:personnes|collaborateurs|salari[ée]s|talents|ing[ée]nieurs|d[ée]veloppeurs|profils"
    r"|postes|recrues|employ[ée]s|commerciaux|chercheurs|experts|data scientists"
    r"|account executives|product managers?)"
)
# Verbs only ("financeront", "finançant"), never the noun "financement".
_FUND_VERBS = (
    r"(?:financ(?:er|era|eront|ent|e)\b|finan[cç]ant|servir\w*\s+à|consacr\w*|d[ée]di\w*"
    r"|allou\w*|soutenir|soutiendr\w*|soutient|poursuivre|acc[ée]l[ée]rer|intensifier"
    r"|accompagner)"
)
_HIRING_PATTERNS: tuple[str, ...] = (
    # "recruter une trentaine de personnes", "recruter 50 ingénieurs", "recruter des profils"
    r"(?:recruter|embaucher)\s+(?:[\w'’-]+\s+){0,3}?" + _PEOPLE,
    # plan frame: "prévoit de recruter", "pour recruter", "servira à recruter"
    r"(?:pr[ée]voi\w*|compte\w*|souhaite\w*|ambitionne\w*|entend\w*|va|vont|afin|pour"
    r"|servir\w*\s+à|permettr\w*\s+de|objectif\s+de)\s+(?:de\s+|d['’])?(?:\w+\s+){0,2}?"
    r"(?:recruter|embaucher)\b",
    # "25 recrutements", "une centaine d'embauches"
    _SIZE_WORDS + r"\s+(?:de\s+|d['’])?(?:recrutements|embauches|postes|recrues)\b",
    # A verb acting on the noun: "les fonds financeront des recrutements", "soutenir les
    # recrutements", "poursuivre ses recrutements", "finançant le recrutement d'équipes".
    # A bare "son recrutement par Anthropic" (a person) has no such verb and never matches.
    _FUND_VERBS + r"\s+(?:[\w'’-]+\s+){0,3}?(?:recrutements|embauches)\b",
    _FUND_VERBS + r"\s+(?:\w+\s+)?(?:le|du)\s+recrutement\s+"
    r"(?:de\s+|d['’])(?:[\w'’-]+\s+){0,1}?(?:[ée]quipes?|" + _PEOPLE[3:-1] + r")",
    # "le recrutement de 30 ingénieurs" (a quantity, never a named person)
    r"(?:recrutement|embauche)\s+(?:de\s+|d['’])" + _SIZE_WORDS + r"\s+(?:de\s+)?" + _PEOPLE,
    # "doubler ses effectifs", "doubler de nouveau ses effectifs", "renforcer son équipe"
    r"(?:doubler|tripler|renforcer|[ée]toffer|agrandir|muscler)\s+(?:de nouveau\s+|encore\s+)?"
    r"(?:ses|son|sa|l['’]|leurs?)\s*(?:effectifs?|[ée]quipes?)",
    r"passer de \d+ à \d+ " + _PEOPLE,
    r"atteindre \d+ " + _PEOPLE,
    # EN: "plans to hire", "will hire", "to recruit", "hire 50 engineers", "is hiring"
    r"\b(?:plans?|aims?|intends?|expects?|will|to|wants?)\s+(?:to\s+)?(?:hire|recruit)\b",
    r"\b(?:hire|recruit)\s+(?:more than |over |up to |about |around )?\d+",
    r"\b(?:is|are)\s+hiring\b",
    r"(?:grow|expand|double|triple|scale)\s+(?:its|the|their|our)\s+"
    r"(?:team|teams|headcount|workforce)",
    r"\b\d+\s+(?:new\s+)?(?:hires|jobs|roles|positions)\b",
)
_HIRING_RES = tuple(re.compile(p, re.IGNORECASE) for p in _HIRING_PATTERNS)


def _hiring_in(sentence: str) -> str | None:
    """Most specific phrase first (patterns are ordered), e.g. "recruter 50 ingénieurs"
    rather than "pour recruter"."""
    if _HIRING_NEGATIVE_RE.search(sentence):
        return None
    cleaned = _HIRING_PRESTRIP_RE.sub("", sentence)
    for regex in _HIRING_RES:
        m = regex.search(cleaned)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


# ---------------------------------------------------------------------------
# Location and country (explicit only)
# ---------------------------------------------------------------------------

# Singular on purpose: "Acme, basée à Lyon" is the company; "des profils basés à Paris" is not.
_LOCATION_RE = re.compile(
    r"(?:bas[ée]e?|install[ée]e?|implant[ée]e?|situ[ée]e?)\s+à\s+"
    r"(?P<loc>[A-ZÀ-Ý][\w'’-]+(?:[ -][A-ZÀ-Ý][\w'’-]+)?)"
    r"|based in\s+(?P<loc_en>[A-Z][\w'’-]+(?: [A-Z][\w'’-]+)?)"
)

_CITY_COUNTRY: dict[str, str] = {
    **{c: "France" for c in (
        "paris", "lyon", "marseille", "bordeaux", "lille", "nantes", "toulouse", "grenoble",
        "rennes", "strasbourg", "nice", "montpellier", "sophia antipolis", "france")},
    **{c: "United Kingdom" for c in ("londres", "london", "royaume-uni", "uk", "united kingdom")},
    **{c: "Germany" for c in ("berlin", "munich", "hambourg", "hamburg", "allemagne", "germany")},
    **{c: "United States" for c in (
        "new york", "san francisco", "boston", "etats-unis", "united states", "us")},
    **{c: "Switzerland" for c in ("zurich", "geneve", "lausanne", "suisse", "switzerland")},
    "stockholm": "Sweden", "amsterdam": "Netherlands", "bruxelles": "Belgium",
    "brussels": "Belgium", "madrid": "Spain", "barcelone": "Spain", "barcelona": "Spain",
    "milan": "Italy", "tel aviv": "Israel", "montreal": "Canada", "copenhague": "Denmark",
    "oslo": "Norway", "helsinki": "Finland", "tallinn": "Estonia", "lisbonne": "Portugal",
    "lisbon": "Portugal", "dublin": "Ireland", "vienne": "Austria", "varsovie": "Poland",
}
_NATIONALITY: dict[str, str] = {
    **{a: "France" for a in (
        "francaise", "francais", "french", "tricolore", "parisienne", "parisien", "lyonnaise",
        "lyonnais", "marseillaise", "bordelaise", "lilloise", "nantaise", "nantais",
        "toulousaine", "toulousain", "grenobloise", "rennaise", "strasbourgeoise", "nicoise",
        "montpellieraine")},
    **{a: "United Kingdom" for a in ("britannique", "anglaise", "londonienne", "british")},
    **{a: "United States" for a in (
        "americaine", "americain", "american", "new-yorkaise", "californienne")},
    **{a: "Germany" for a in ("allemande", "allemand", "german", "berlinoise", "munichoise")},
    **{a: "Switzerland" for a in ("suisse", "swiss")},
    **{a: "Sweden" for a in ("suedoise", "swedish")},
    **{a: "Spain" for a in ("espagnole", "spanish")},
    **{a: "Italy" for a in ("italienne", "italian")},
    **{a: "Netherlands" for a in ("neerlandaise", "dutch")},
    **{a: "Belgium" for a in ("belge", "belgian")},
    **{a: "Denmark" for a in ("danoise", "danish")},
    **{a: "Norway" for a in ("norvegienne", "norwegian")},
    **{a: "Finland" for a in ("finlandaise", "finnish")},
    **{a: "Israel" for a in ("israelienne", "israeli")},
    **{a: "Canada" for a in ("canadienne", "canadian")},
    **{a: "Estonia" for a in ("estonienne", "estonian")},
    **{a: "Ireland" for a in ("irlandaise", "irish")},
    **{a: "Portugal" for a in ("portugaise", "portuguese")},
    **{a: "Austria" for a in ("autrichienne", "austrian")},
    **{a: "Poland" for a in ("polonaise", "polish")},
    **{a: "China" for a in ("chinoise", "chinese")},
}
# The adjective must qualify the company: "la startup suisse", "la pépite britannique",
# "French startup", "London-based". "Le fonds américain Accel" is an investor, not matched.
_COMPANY_NOUNS = (
    r"(?:startup|start-up|soci[ée]t[ée]|entreprise|p[ée]pite|scale-up|scaleup|licorne|fintech"
    r"|healthtech|deeptech|medtech|biotech|edtech|insurtech|proptech|legaltech|greentech"
    r"|foodtech|cleantech|jeune pousse|plateforme)"
)
_ADJ = r"(?P<adj>[a-zà-ÿ-]+)"
_NATIONALITY_RES = (
    re.compile(_COMPANY_NOUNS + r"\s+" + _ADJ, re.IGNORECASE),
    re.compile(r"\b" + _ADJ + r"\s+(?:startup|start-up|company|scale-up|fintech|unicorn)",
               re.IGNORECASE),
    re.compile(r"\b(?P<city>[A-Z][\w]+(?: [A-Z][\w]+)?)-based\b"),
)


def _location_in(sentence: str) -> str | None:
    m = _LOCATION_RE.search(sentence)
    return (m.group("loc") or m.group("loc_en")) if m else None


def _country_in(sentence: str) -> str | None:
    for regex in _NATIONALITY_RES:
        for m in regex.finditer(sentence):
            key = normalize_text(m.group("adj") if "adj" in regex.groupindex else m.group("city"))
            country = _NATIONALITY.get(key) or _CITY_COUNTRY.get(key)
            if country:
                return country
    loc = _location_in(sentence)
    return _CITY_COUNTRY.get(normalize_text(loc)) if loc else None


# ---------------------------------------------------------------------------
# Article structure: paragraphs, briefs, anchor scope
# ---------------------------------------------------------------------------

_BRIEF_SEPARATOR = " / "  # FrenchWeb daily briefs: "A lève 5 M€ / B rachète C / D ..."
_HIRING_WINDOW = 3  # sentences after the anchor sentence, same paragraph

# A sentence "refers back" to the raise ("Le financement…", "Les fonds…", "Les 35 millions
# d'euros…") or to the company (its name, or a leading "Elle"/"L'entreprise"/"La startup").
_TIE_BACK_RE = re.compile(
    r"\b(?:le financement|ce financement|les fonds|cette lev[ée]e|ce tour|les capitaux"
    r"|cette op[ée]ration|ce montant|cette somme|the funding|the funds|the round|the capital"
    r"|the new capital)\b"
    r"|\bles \d+(?:[.,]\d+)? (?:millions|milliards?|M€|M\$)"
    r"|^(?:elle|l['’]entreprise|la startup|la soci[ée]t[ée]|la jeune pousse|la scale-up"
    r"|the company|it)\b",
    re.IGNORECASE,
)


def _ties_back(sentence: str, company: str) -> bool:
    return bool(_TIE_BACK_RE.search(sentence)) or _mentions(sentence, company)
_TERMINAL_RE = re.compile(r"[.!?…»\"”)]\s*$")


@dataclass(frozen=True, slots=True)
class _Sent:
    text: str
    para: int  # -1 = title (or a title segment in a brief), 0.. = body paragraphs


def split_paragraphs(text: str) -> list[list[str]]:
    """Body paragraphs (one per non-empty line, bullets included), each split into sentences."""
    return [s for s in (split_sentences(line) for line in (text or "").split("\n")) if s]


def is_brief(title: str) -> bool:
    return _BRIEF_SEPARATOR in (title or "")


def _structure(title: str, text: str) -> list[_Sent]:
    title = title or ""
    segments = title.split(_BRIEF_SEPARATOR) if is_brief(title) else [title]
    sents = [_Sent(s, -1) for seg in segments for s in split_sentences(seg)]
    for i, para in enumerate(split_paragraphs(text)):
        sents.extend(_Sent(s, i) for s in para)
    return sents


def _mentions(sentence: str, company: str) -> bool:
    c = normalize_company(company)
    return bool(c) and re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)",
                                 normalize_text(sentence)) is not None


def _is_heading(paragraph: list[_Sent]) -> bool:
    """A one-line paragraph without final punctuation: a subheading over the next paragraph."""
    return len(paragraph) == 1 and not _TERMINAL_RE.search(paragraph[0].text)


def _scope(
    sents: list[_Sent], main: _Sent, company: str | None, funding_texts: set[str], brief: bool
) -> list[_Sent]:
    """Body sentences that belong to the company's story, in order.

    The anchor paragraph is the one holding the anchor sentence. When the anchor is the title,
    it is the first body paragraph with a funding sentence or the company name (non-brief
    articles fall back to the lede). A heading paragraph is merged with the next paragraph.
    """
    paras: dict[int, list[_Sent]] = {}
    for s in sents:
        if s.para >= 0:
            paras.setdefault(s.para, []).append(s)
    if main.para >= 0:
        anchor = main.para
    else:
        anchor = next(
            (i for i, p in sorted(paras.items())
             if any(s.text in funding_texts or (company and _mentions(s.text, company))
                    for s in p)),
            None,
        )
        if anchor is None and not brief and paras:
            anchor = min(paras)
    if anchor is None:
        return []
    scope = list(paras[anchor])
    if _is_heading(paras[anchor]) and anchor + 1 in paras:
        scope += paras[anchor + 1]
    return scope


def _hiring_window(main: _Sent, scope: list[_Sent], company: str | None,
                   funding_texts: set[str]) -> list[_Sent]:
    """Anchor sentence + the next 3 sentences of its paragraph (title anchor: + scope start)."""
    if not scope:
        return [main]
    if main in scope:
        start = scope.index(main)
        return scope[start : start + 1 + _HIRING_WINDOW]
    start = next(
        (i for i, s in enumerate(scope)
         if s.text in funding_texts or (company and _mentions(s.text, company))),
        0,
    )
    return [main] + scope[start : start + 1 + _HIRING_WINDOW]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ev(sentence: str) -> str:
    return sentence[:MAX_EVIDENCE_CHARS]


def extract_funding(title: str, text: str) -> FundingExtraction:
    """One extraction per article: the first funding sentence with a company anchors it.

    Briefs (titles with " / ") are multi-topic: every field comes only from the anchor
    sentence and its paragraph. In all articles the hiring signal comes only from the anchor
    sentence and the next 3 sentences of the same paragraph.
    """
    brief = is_brief(title)
    sents = _structure(title, text)
    candidates = [(s, _as_funding_sentence(s.text)) for s in sents]
    funding = [(s, fs) for s, fs in candidates if fs is not None]
    if not funding:
        return FundingExtraction(is_funding=False)

    company: str | None = None
    anchor_i = 0
    for i, (_, fs) in enumerate(funding):
        company = _company_before(fs.text, fs.anchor)
        if company:
            anchor_i = i
            break
    main, main_fs = funding[anchor_i]
    funding_texts = {s.text for s, _ in funding}
    scope = _scope(sents, main, company, funding_texts, brief)

    if brief:
        # Only the anchor sentence and its paragraph: never another topic of the brief.
        allowed = {id(main)} | {id(s) for s in scope}
        scoped_funding = [fs for s, fs in funding[anchor_i:] if id(s) in allowed]
        after = [s.text for s in scope if s is not main and not _is_guarded_sentence(s.text)]
        others = after
    else:
        scoped_funding = [fs for _, fs in funding[anchor_i:]]
        main_idx = sents.index(main)
        after = [s.text for s in sents[main_idx + 1 :] if not _is_guarded_sentence(s.text)]
        others = [s.text for s in sents if not _is_guarded_sentence(s.text)]

    evidence: dict[str, str] = {"funding": _ev(main_fs.text)}
    if company:
        evidence["company"] = _ev(main_fs.text)

    amount: float | None = None
    currency: str | None = None
    for fs in scoped_funding:
        best = _nearest_amount(fs)
        if best is not None:
            amount, currency = best.value, best.currency
            evidence["amount"] = _ev(fs.text)
            break

    round_: str | None = None
    for s in [fs.text for fs in scoped_funding] + after:
        round_ = _round_in(s)
        if round_:
            evidence["round"] = _ev(s)
            break

    investors: tuple[str, ...] | None = None
    for s in [main_fs.text] + after:
        if _is_guarded_sentence(s):
            continue
        investors = _investors_in(s, company)
        if investors:
            evidence["investors"] = _ev(s)
            break

    hiring: str | None = None
    for s in _hiring_window(main, scope, company, funding_texts):
        if _is_guarded_sentence(s.text):
            continue
        hiring = _hiring_in(s.text)
        if hiring:
            evidence["hiring"] = _ev(s.text)
            break
    if hiring is None and not brief and company:
        # Single-topic article: the "use of funds" paragraph is often further down. Accept it
        # only when the sentence explicitly refers back to the raise or the company.
        for s in sents:
            if s.para < 0 or _is_guarded_sentence(s.text) or not _ties_back(s.text, company):
                continue
            hiring = _hiring_in(s.text)
            if hiring:
                evidence["hiring"] = _ev(s.text)
                break

    location: str | None = None
    for s in [main_fs.text] + others:
        location = _location_in(s)
        if location:
            evidence["location"] = _ev(s)
            break

    country: str | None = None
    for s in [main_fs.text] + [x.text for x in scope]:
        country = _country_in(s)
        if country:
            evidence["country"] = _ev(s)
            break

    return FundingExtraction(
        is_funding=True,
        company=company,
        amount=amount,
        currency=currency,
        round=round_,
        investors=investors,
        hiring=hiring,
        location=location,
        country=country,
        evidence=evidence,
    )


def format_amount(amount: float | None, currency: str | None) -> str | None:
    """Human-readable amount: ``10 M€``, ``1,5 Md€``, ``$5M``, ``$1.2B``, ``300 k€``."""
    if amount is None:
        return None
    if amount >= 1e9:
        value, scale_fr, scale_en = amount / 1e9, "Md", "B"
    elif amount >= 1e6:
        value, scale_fr, scale_en = amount / 1e6, "M", "M"
    elif amount >= 1e3:
        value, scale_fr, scale_en = amount / 1e3, "k", "k"
    else:
        value, scale_fr, scale_en = amount, "", ""
    number = f"{value:.2f}".rstrip("0").rstrip(".")
    if currency == "USD":
        return f"${number}{scale_en}"
    symbol = {"EUR": "€", "GBP": "£"}.get(currency or "", "")
    return f"{number.replace('.', ',')} {scale_fr}{symbol}".strip()
