"""Name and company normalization: ASCII folding, name parsing, nicknames.

Deterministic and offline. The outputs feed identity resolution
(``identity.py``) and the email pattern engine (``patterns.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from unidecode import unidecode

SUFFIXES: tuple[str, ...] = (
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "v",
    "phd",
    "md",
    "mba",
    "esq",
    "cpa",
    "dds",
    "rn",
    "jd",
)

PARTICLES: tuple[str, ...] = (
    "van",
    "von",
    "de",
    "del",
    "della",
    "der",
    "den",
    "da",
    "di",
    "la",
    "le",
    "el",
    "al",
    "bin",
    "ibn",
    "ter",
    "ten",
    "op",
)

NICKNAMES: dict[str, str] = {
    "al": "albert",
    "alex": "alexander",
    "andy": "andrew",
    "drew": "andrew",
    "bob": "robert",
    "bobby": "robert",
    "rob": "robert",
    "robbie": "robert",
    "bill": "william",
    "billy": "william",
    "will": "william",
    "willy": "william",
    "liam": "william",
    "jim": "james",
    "jimmy": "james",
    "jamie": "james",
    "mike": "michael",
    "mikey": "michael",
    "mick": "michael",
    "dave": "david",
    "davey": "david",
    "joe": "joseph",
    "joey": "joseph",
    "tom": "thomas",
    "tommy": "thomas",
    "dick": "richard",
    "rick": "richard",
    "rich": "richard",
    "richie": "richard",
    "liz": "elizabeth",
    "lizzy": "elizabeth",
    "beth": "elizabeth",
    "betsy": "elizabeth",
    "eliza": "elizabeth",
    "lisa": "elizabeth",
    "kate": "katherine",
    "katie": "katherine",
    "kathy": "katherine",
    "kat": "katherine",
    "cathy": "katherine",
    "peg": "margaret",
    "peggy": "margaret",
    "maggie": "margaret",
    "meg": "margaret",
    "sue": "susan",
    "susie": "susan",
    "suzy": "susan",
    "jenn": "jennifer",
    "jenny": "jennifer",
    "jen": "jennifer",
    "chris": "christopher",
    "topher": "christopher",
    "nick": "nicholas",
    "nicky": "nicholas",
    "tony": "anthony",
    "ed": "edward",
    "eddie": "edward",
    "ted": "edward",
    "teddy": "edward",
    "sam": "samuel",
    "sammy": "samuel",
    "ben": "benjamin",
    "benny": "benjamin",
    "dan": "daniel",
    "danny": "daniel",
    "pat": "patrick",
    "paddy": "patrick",
    "steve": "steven",
    "stevie": "steven",
    "greg": "gregory",
    "jeff": "jeffrey",
    "pete": "peter",
    "phil": "philip",
    "vince": "vincent",
    "vinny": "vincent",
    "walt": "walter",
    "wally": "walter",
    "ron": "ronald",
    "ronnie": "ronald",
    "don": "donald",
    "donnie": "donald",
    "ken": "kenneth",
    "kenny": "kenneth",
    "larry": "lawrence",
    "frank": "francis",
    "frankie": "francis",
    "charlie": "charles",
    "chuck": "charles",
    "hank": "henry",
    "harry": "henry",
    "jack": "john",
    "johnny": "john",
    "jon": "john",
    "gabe": "gabriel",
    "gabby": "gabriel",
}

COMPANY_SUFFIXES: tuple[str, ...] = (
    "inc",
    "llc",
    "ltd",
    "corp",
    "corporation",
    "co",
    "gmbh",
    "plc",
    "pty",
    "sa",
    "ag",
    "bv",
    "nv",
    "ab",
    "oy",
    "as",
    "srl",
    "spa",
    "kk",
    "pte",
    "limited",
    "group",
    "holdings",
    "technologies",
)

_SUFFIX_SET = frozenset(SUFFIXES)
_PARTICLE_SET = frozenset(PARTICLES)
_COMPANY_SUFFIX_SET = frozenset(COMPANY_SUFFIXES)

_UNKNOWN = "unknown"


def fold_ascii(value: str) -> str:
    """Transliterate to ASCII, lowercase, keep [a-z0-9], collapse separators.

    Hyphens become single spaces; every other punctuation mark is dropped in
    favour of a space as well, and runs of whitespace collapse to one space.
    """
    if not value:
        return ""
    try:
        text = unidecode(value)
    except Exception:  # pragma: no cover - unidecode is very tolerant
        text = value
    text = text.lower().replace("-", " ")
    kept = [
        ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else " "
        for ch in text
    ]
    return " ".join("".join(kept).split())


def canonical_first_name(first: str) -> str:
    """Map a folded first name through the nickname table."""
    key = fold_ascii(first)
    return NICKNAMES.get(key, key)


def _last_variants(last: str) -> tuple[str, ...]:
    """Joined (spaces removed) and final-token variants of a last name."""
    if not last:
        return ()
    tokens = last.split()
    joined = last.replace(" ", "")
    variants: list[str] = []
    if joined:
        variants.append(joined)
    token = tokens[-1] if tokens else last
    if token and token != joined:
        variants.append(token)
    return tuple(variants)


def _strip_trailing_suffixes(tokens: list[str]) -> list[str]:
    while tokens and tokens[-1] in _SUFFIX_SET:
        tokens.pop()
    return tokens


@dataclass(frozen=True)
class NameParts:
    full_name: str
    first: str
    middle: str | None
    last: str
    name_key: str
    initials: str
    last_variants: tuple[str, ...]


def normalize_name(raw: str) -> NameParts:
    """Split a display name into folded, comparable parts.

    Handles ``Jane Doe``, ``Doe, Jane``, middle names, generational/professional
    suffixes, and particles that belong with the last name. Never raises on
    non-Latin input; falls back to a non-empty placeholder.
    """
    cleaned = " ".join((raw or "").split())
    first_part, last_part = cleaned, ""
    if "," in cleaned:
        last_part, _, first_part = cleaned.partition(",")

    first_tokens = _strip_trailing_suffixes(fold_ascii(first_part).split())
    last_tokens = _strip_trailing_suffixes(fold_ascii(last_part).split())

    if last_tokens:
        last = " ".join(last_tokens)
        if first_tokens:
            first = first_tokens[0]
            middle = " ".join(first_tokens[1:]) or None
        else:
            first = last_tokens[0]
            middle = None
    elif not first_tokens:
        first = last = _UNKNOWN
        middle = None
    elif len(first_tokens) == 1:
        first = last = first_tokens[0]
        middle = None
    else:
        index = len(first_tokens) - 1
        while index >= 1 and first_tokens[index] in _PARTICLE_SET:
            index -= 1
        start = index
        while start - 1 >= 1 and first_tokens[start - 1] in _PARTICLE_SET:
            start -= 1
        if start <= 0:
            first = first_tokens[0]
            last = " ".join(first_tokens[1:]) or first_tokens[0]
            middle = None
        else:
            first = first_tokens[0]
            middle = " ".join(first_tokens[1:start]) or None
            last = " ".join(first_tokens[start:])

    return NameParts(
        full_name=cleaned or _UNKNOWN,
        first=first,
        middle=middle,
        last=last,
        name_key=f"{canonical_first_name(first)} {last}".strip(),
        initials=f"{first[:1]}{last[:1]}",
        last_variants=_last_variants(last),
    )


def normalize_company(raw: str) -> str:
    """Normalized company key: folded, leading "the" and legal forms stripped."""
    folded = fold_ascii(raw or "")
    tokens = folded.split()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    while tokens and tokens[-1] in _COMPANY_SUFFIX_SET:
        tokens.pop()
    if not tokens:
        return folded
    return " ".join(tokens)
