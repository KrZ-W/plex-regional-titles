import pytest

from plex_regional_titles.normalize import (
    clean_registry_title,
    match_key,
    norm,
    strip_version_suffix,
    uninvert_article,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Élève libre", "eleve libre"),
        ("L'Épée du Cid !", "l epee du cid"),
        ("G.I. Jane", "g i jane"),
        ("  Café -- crème  ", "cafe creme"),
        ("Frost/Nixon", "frost nixon"),
        ("Ｆｕｌｌｗｉｄｔｈ", "fullwidth"),
        ("", ""),
        (None, ""),
        ("Œdipe", "oedipe"),
    ],
)
def test_norm(raw, expected):
    assert norm(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("CHUTE DE L'EMPIRE ROMAIN, LA", "LA CHUTE DE L'EMPIRE ROMAIN"),
        ("FALL OF THE ROMAN EMPIRE, THE ", "THE FALL OF THE ROMAN EMPIRE"),
        ("épée du Cid, L'", "L'épée du Cid"),
        ("épée du Cid, L", "L'épée du Cid"),
        ("INCROYABLE, LES", "LES INCROYABLE"),
        ("Homme, Un", "Un Homme"),
        ("Femme, Une", "Une Femme"),
        ("Hommes, Des", "Des Hommes"),
        ("Beautiful Mind, A", "A Beautiful Mind"),
        ("American Tail, An", "An American Tail"),
        ("Bonnie, Clyde", "Bonnie, Clyde"),
        ("No inversion", "No inversion"),
        ("PARIS, TEXAS", "PARIS, TEXAS"),
        ("FILM LEGO, LE -", "LE FILM LEGO"),
        ("AUBE DE LA PLANETE DES SINGES, L' - ", "L'AUBE DE LA PLANETE DES SINGES"),
        ("INTERVIEW QUI TUE, L' !", "L'INTERVIEW QUI TUE!"),
        ("EXODE - DIEUX ET ROIS, L' -", "L'EXODE - DIEUX ET ROIS"),
    ],
)
def test_uninvert_article(raw, expected):
    assert uninvert_article(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("G.I. JANE (V.F.)", "G.I. JANE"),
        ("POSTAL (V.F.) ", "POSTAL"),
        ("HUGO (V.F)", "HUGO"),
        ("TITRE (V.O.A.)", "TITRE"),
        ("TITRE (V.O.F.)", "TITRE"),
        ("TITRE (V.O.A.S.-T.F.)", "TITRE"),
        ("TITRE (FR.)", "TITRE"),
        ("PONYO (V.A.)", "PONYO"),
        ("MOANA (V.F.) (V.O.A.)", "MOANA"),
        ("SEVEN (TZAMETI)", "SEVEN (TZAMETI)"),
        ("LOL (LAUGHING OUT LOUD)", "LOL (LAUGHING OUT LOUD)"),
    ],
)
def test_strip_version_suffix(raw, expected):
    assert strip_version_suffix(raw) == expected


def test_clean_registry_title_combined():
    assert clean_registry_title("CHUTE DE L'EMPIRE ROMAIN, LA (V.F.)") == "LA CHUTE DE L'EMPIRE ROMAIN"
    assert clean_registry_title("YULI (ESPAGNOL)") == "YULI"


def test_match_key_equivalences():
    assert match_key("CHUTE DE L'EMPIRE ROMAIN, LA ") == match_key("La Chute de l'Empire romain")
    assert match_key("G.I. JANE (V.F.)") == match_key("G.I. Jane")
    assert match_key("ERIN BROCKOVICH") == match_key("Erin Brockovich")
