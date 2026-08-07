"""Judge prompt/parse contract — single verdicts, batched verdicts, and the
prompt builder's structure (the exact judge.py contract)."""
from pipeline import judging

PROFILE = {
    "version": "v-test",
    "core_statement": "I study X.",
    "flavors": [{"key": "flavor_a", "description": "A-things"},
                {"key": "flavor_b", "description": "B-things"}],
    "fit_rule": "One flavor is a bullseye.",
    "negatives": ["Nothing about Z"],
    "positive_exemplar_titles": ["Great paper one"],
    "negative_exemplar_titles": ["Bad paper one"],
}


def test_build_prompt_contains_contract_sections():
    p = judging.build_prompt(PROFILE, extra_pos=["Voted up"], extra_neg=["Voted down"])
    for needle in ("RESEARCHER PROFILE:", "EXPLICITLY NOT OF INTEREST:",
                   "PAPERS THE RESEARCHER LIKED:", "INTEREST FLAVORS",
                   "FIT RULE:", "STRICT JSON",
                   "- flavor_a: A-things", "Voted up (recent 👍)",
                   "Voted down (recent 👎)", "Great paper one"):
        assert needle in p


def test_build_prompt_legacy_facets():
    prof = {"core_statement": "X", "facets": [
        {"key": "f1", "core": True, "description": "d1"}],
        "intersection_rule": "rule here"}
    p = judging.build_prompt(prof)
    assert "FACETS:" in p and "f1 (CORE)" in p and "INTERSECTION RULE: rule here" in p


def test_parse_single_valid_and_messy():
    v = judging.parse_single('{"facets": ["a"], "fit": 8, "why": "yes"}')
    assert v == {"facets": ["a"], "fit": 8.0, "why": "yes"}
    v = judging.parse_single('Sure! Here you go:\n{"facets": [], "fit": 3.5, "why": "meh"}\nDone.')
    assert v["fit"] == 3.5
    assert judging.parse_single("no json at all") is None
    assert judging.parse_single('{"fit": 15, "why": "out of range"}') is None
    assert judging.parse_single('{"fit": -2}') is None
    assert judging.parse_single("") is None
    long = judging.parse_single(json_why_300())
    assert len(long["why"]) == 300                       # rationale is capped


def json_why_300():
    return '{"facets": [], "fit": 5, "why": "' + "w" * 400 + '"}'


def test_parse_batch_contract():
    txt = ('[{"n": 1, "facets": ["a"], "fit": 9, "why": "one"}, '
           '{"n": 2, "facets": [], "fit": 2, "why": "two"}]')
    out = judging.parse_batch(txt, 2)
    assert out[1]["fit"] == 9.0 and out[2]["why"] == "two"


def test_parse_batch_partial_and_bad_rows():
    txt = ('[{"n": 1, "fit": 7, "why": "ok"}, {"n": 5, "fit": 3, "why": "index oob"}, '
           '{"n": 2, "fit": 99, "why": "bad fit"}]')
    out = judging.parse_batch(txt, 3)
    assert set(out) == {1}                               # oob + bad fit dropped
    assert judging.parse_batch("not a list", 3) is None
    assert judging.parse_batch("[]", 3) is None


def test_judge_batch_aligns_failures():
    papers = [{"title": f"P{i}", "venue": "V", "abstract": "A"} for i in range(3)]

    def chat_fn(system, user, temperature):
        assert temperature == 0.0
        assert "PAPER 1:" in user and "PAPER 3:" in user
        return ('[{"n": 1, "facets": [], "fit": 8, "why": "hit"},'
                ' {"n": 3, "facets": [], "fit": 1, "why": "miss"}]', "groq")

    verdicts, provider = judging.judge_batch("SYS", papers, chat_fn)
    assert provider == "groq"
    assert [v["fit"] for v in verdicts] == [8.0, -1, 1.0]
    assert verdicts[1]["why"] == "batch parse failed"


def test_judge_batch_total_failure_after_retries():
    calls = []

    def chat_fn(system, user, temperature):
        calls.append(1)
        return "garbage", "gemini"

    verdicts, _ = judging.judge_batch("SYS", [{"title": "T"}], chat_fn)
    assert len(calls) == 3                               # 3 parse attempts
    assert verdicts[0]["fit"] == -1
    assert verdicts[0]["why"] == "batch call failed"
