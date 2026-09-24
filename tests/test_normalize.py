from __future__ import annotations

from bucketio.normalize import (
    NICKNAMES,
    PARTICLES,
    SUFFIXES,
    NameParts,
    canonical_first_name,
    fold_ascii,
    normalize_company,
    normalize_name,
)


def test_nicknames_cover_required_pairs():
    assert NICKNAMES["bob"] == "robert"
    assert NICKNAMES["liz"] == "elizabeth"
    assert NICKNAMES["jim"] == "james"
    assert NICKNAMES["mike"] == "michael"
    assert len(NICKNAMES) >= 50


def test_suffixes_and_particles_are_complete():
    for suffix in (
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
    ):
        assert suffix in SUFFIXES
    for particle in (
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
    ):
        assert particle in PARTICLES


def test_fold_ascii():
    assert fold_ascii("José García") == "jose garcia"
    assert fold_ascii("  Van der Berg  ") == "van der berg"
    assert fold_ascii("Smith-Jones") == "smith jones"
    assert fold_ascii("O'Brien") == "o brien"
    assert fold_ascii("") == ""
    assert fold_ascii(None) == ""


def test_bob_and_robert_share_name_key():
    bob = normalize_name("Bob Smith")
    robert = normalize_name("Robert Smith")
    assert bob.name_key == robert.name_key == "robert smith"
    assert bob.first == "bob"
    assert bob.last == "smith"
    assert bob.full_name == "Bob Smith"
    assert bob.initials == "bs"


def test_company_keys_collapse_legal_suffixes():
    assert normalize_company("ACME Corp") == "acme"
    assert normalize_company("Acme Inc") == "acme"
    assert normalize_company("Acme, Inc.") == "acme"
    assert normalize_company("The Acme Corporation") == "acme"
    assert normalize_company("Acme Inc") == normalize_company("ACME Corp")
    assert normalize_company("Acme Inc") != normalize_company("Acme Labs")
    assert normalize_company("Acme Labs") == "acme labs"
    assert normalize_company("Acme Group") == "acme"
    assert normalize_company("Acme Holdings Ltd") == "acme"


def test_comma_form_is_last_first():
    parts = normalize_name("Doe, Jane")
    assert (parts.first, parts.middle, parts.last) == ("jane", None, "doe")
    assert parts.full_name == "Doe, Jane"
    assert parts.name_key == "jane doe"


def test_suffixes_dropped():
    parts = normalize_name("Robert Smith Jr.")
    assert (parts.first, parts.last) == ("robert", "smith")
    assert parts.full_name == "Robert Smith Jr."
    assert normalize_name("Jane Doe PhD").last == "doe"
    assert normalize_name("Smith, Robert III").last == "smith"
    assert normalize_name("Smith, Robert III").first == "robert"


def test_particles_stay_with_last_name():
    parts = normalize_name("Jane van der Berg")
    assert parts.first == "jane"
    assert parts.last == "van der berg"
    assert parts.last_variants == ("vanderberg", "berg")
    assert parts.initials == "jv"
    assert parts.name_key == "jane van der berg"


def test_middle_names_and_whitespace():
    parts = normalize_name("  Jane   Q.  Doe ")
    assert (parts.first, parts.middle, parts.last) == ("jane", "q", "doe")
    assert parts.full_name == "Jane Q. Doe"
    assert normalize_name("Mary Jo van der Berg").middle == "jo"
    assert normalize_name("Mary Jo van der Berg").last == "van der berg"


def test_single_token_name_falls_back():
    parts = normalize_name("Madonna")
    assert parts.first == "madonna"
    assert parts.last == "madonna"
    assert parts.last_variants == ("madonna",)


def test_cyrillic_input_does_not_raise():
    parts = normalize_name("Анна Иванова")
    assert isinstance(parts, NameParts)
    assert parts.first == "anna"
    assert parts.last == "ivanova"
    assert parts.last != ""


def test_cjk_input_does_not_raise():
    parts = normalize_name("张三")
    assert parts.last != ""
    assert parts.name_key


def test_empty_and_punctuation_inputs_fall_back():
    for raw in ("", "   ", "!!!", ",", None):
        parts = normalize_name(raw)
        assert parts.last != ""
        assert parts.last != ""
        assert parts.name_key
    assert normalize_name("   ").last == "unknown"


def test_canonical_first_name():
    assert canonical_first_name("Bob") == "robert"
    assert canonical_first_name("JANE") == "jane"
    assert canonical_first_name("Jane") == "jane"
