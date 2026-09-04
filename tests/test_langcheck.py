"""Language screen: the stopword heuristic, the gather.keep() gate, and the
one-shot corpus scrub. The French fixture is the actual SocArXiv abstract
that reached the 2026-09-04 briefing."""
from __future__ import annotations

from app.langcheck import looks_english

FRENCH = ("Cette contribution tente d'abord de montrer l'impact négatif des "
          "polarisations idéologiques aiguës sur la transition démocratique "
          "en prenant comme exemples les expériences de l'Algérie, de "
          "l'Egypte, de la Libye, du Maroc et de la Tunisie. Elle examine "
          "ensuite la scène politique en Afrique du Nord et les tensions "
          "idéologiques en son sein et souligne l'importance d'éviter le "
          "piège de considérer les courants idéologiques nord-africains "
          "comme des blocs monolithiques mais plutôt comme des spectres "
          "larges comprenant des acteurs aux attitudes et comportements "
          "politiques variés.")

ENGLISH = ("We study how narratives persuade people across political "
           "divides using a preregistered experiment with a national "
           "sample, and find that the effect of exposure on attitudes is "
           "moderated by prior beliefs about the source of the message.")

SPANISH = ("Este artículo analiza la polarización política en América "
           "Latina y sus efectos sobre la democracia, con datos de una "
           "encuesta que muestra cómo los ciudadanos perciben a los "
           "partidos y sus líderes en un contexto de crisis institucional.")


def test_english_passes_and_french_fails():
    assert looks_english(ENGLISH)
    assert not looks_english("Dépolarisation idéologique en Afrique du Nord "
                             + FRENCH)


def test_spanish_fails():
    assert not looks_english(SPANISH)


def test_short_or_ambiguous_text_kept():
    assert looks_english("")                       # no signal -> keep
    assert looks_english("Dépolarisation idéologique en Afrique du Nord")
    assert looks_english("Deep learning for panel data")
    # technical English with few stopwords still passes
    assert looks_english("Transformer models improve stance detection "
                         "accuracy across seventeen benchmark datasets "
                         "spanning politics health science misinformation")


def test_gather_keep_screens_content(test_db):
    from pipeline import gather
    base = {"doi": "10.1/x", "type": "preprint", "date": "2026-09-01"}
    assert gather.keep({**base, "title": "Narrative persuasion in politics",
                        "abstract": ENGLISH})
    assert not gather.keep({**base,
                            "title": "Dépolarisation idéologique en Afrique",
                            "abstract": FRENCH})
    # declared language still wins over content
    assert not gather.keep({**base, "language": "fr",
                            "title": "An english-looking title here",
                            "abstract": ENGLISH})


def test_scrub_migration_removes_unseen_non_english(test_db):
    from app import db as appdb
    con = test_db
    rows = [("k-en", "Narrative persuasion in online politics", ENGLISH),
            ("k-fr", "Dépolarisation idéologique en Afrique du Nord", FRENCH),
            ("k-fr-briefed", "Une autre contribution en français", FRENCH)]
    ids = {}
    for k, title, abstract in rows:
        cur = con.execute(
            "INSERT INTO papers(key, title, abstract, first_seen) "
            "VALUES(?,?,?,?)", (k, title, abstract, appdb.now()))
        ids[k] = cur.lastrowid
    con.execute("INSERT INTO users(email, created_at) VALUES('u@x.com', ?)",
                (appdb.now(),))
    con.execute(
        "INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
        "VALUES(1, '2026-09-04', ?, 1, 7)", (ids["k-fr-briefed"],))
    con.commit()
    appdb._scrub_non_english(con)
    left = {r["key"] for r in con.execute("SELECT key FROM papers").fetchall()}
    assert "k-en" in left                 # English kept
    assert "k-fr" not in left             # unseen French removed
    assert "k-fr-briefed" in left         # already-briefed history kept
