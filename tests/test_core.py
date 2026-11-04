import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bdr import core  # noqa: E402

FX = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "replies.json").read_text())


def test_fixture_routing_and_language():
    for f in FX:
        p = core.plan(category=f["expected"], email=f["from"], persona_key=f["persona_key"],
                      country=f["country"], first_name=f["first_name"], last_name=f["last_name"],
                      lead_status="Information Qualified (IQL)", member_status="Sent",
                      subject=f["subject"], original_text=f["body"])
        assert p["rep"]["key"] == f["expected_rep"], f["id"]
        assert p["language"] == f["expected_lang"], f["id"]


def test_mql_only_for_engaged():
    for cat, mql in [("interested", True), ("question", True), ("not_interested", False),
                     ("unsubscribe", False), ("referral", False), ("auto_reply", False), ("left_org", False)]:
        p = core.plan(category=cat, email="a@b.nl", persona_key="NL-GEN", country="Netherlands",
                      lead_status="Information Qualified (IQL)", member_status="Sent")
        assert ("lead_status" in p["salesforce"]) == mql, cat


def test_never_downgrade():
    assert core.next_lead_status("Sales Qualified (SQL)", True) is None
    assert core.next_lead_status("Unqualified", True) is None
    assert core.next_lead_status("Information Qualified (IQL)", True) == "Marketing Qualified (MQL)"
    assert core.next_campaign_status("Meeting Booked", "Responded") is None
    assert core.next_campaign_status("Sent", "Responded") == "Responded"


def test_auto_reply_touches_nothing_in_salesforce():
    p = core.plan(category="auto_reply", email="a@b.fr", persona_key="FR-GEN", country="France",
                  lead_status="Information Qualified (IQL)", member_status="Sent")
    assert p["salesforce"] == {}
    assert "reply" not in p["gmail"] and "forward" not in p["gmail"]


def test_booking_link_and_template():
    p = core.plan(category="interested", email="x@y.dk", persona_key="NORDICS-GEN", country=None,
                  first_name="Mette", member_status="Sent", lead_status="Information Qualified (IQL)")
    assert p["booking_link"] == "https://calendly.com/kielgast/go_demo_vocal?utm_source=persona-reachout"
    assert p["gmail"]["reply"]["body"].startswith("Hej Mette,")
    assert p["booking_link"] in p["gmail"]["reply"]["body"]


def test_unsubscribe_opts_out():
    p = core.plan(category="unsubscribe", email="a@b.gov", persona_key="NAM-GEN", country="United States",
                  member_status="Sent", lead_status="Information Qualified (IQL)")
    assert p["salesforce"]["email_opt_out"] is True


def test_language_without_persona_key_uses_country():
    assert core.language_for(None, "belgium") == "nl-BE"
    assert core.language_for("", "germany") == "de"
    assert core.language_for(None, "chile") == "en-US"
    assert core.language_for(None, "belgium", reply_lang="fr") == "fr"


def test_question_gets_ack_and_forward():
    p = core.plan(category="question", email="j@b.de", persona_key="DACH-GEN", country="Germany",
                  first_name="Jonas", last_name="Becker", member_status="Sent",
                  lead_status="Information Qualified (IQL)", subject="AW: Beteiligung zwischen den Ämtern")
    assert p["gmail"]["reply"]["body"].startswith("Guten Tag Jonas Becker,")
    assert "eva-mayer-go-vocal/go_demo_vocal" in p["gmail"]["reply"]["body"]
    assert "forward" in p["gmail"]


def test_referral_reply_only_with_a_name():
    with_name = core.plan(category="referral", email="p@b.be", persona_key="BE-DIR-S", country="Belgium",
                          first_name="Pieter", member_status="Sent", referral_name="An Peeters")
    assert "An Peeters" in with_name["gmail"]["reply"]["body"]
    assert "An Peeters" in with_name["gmail"]["forward"]["body"]
    without = core.plan(category="referral", email="p@b.be", persona_key="BE-DIR-S", country="Belgium",
                        first_name="Pieter", member_status="Sent")
    assert "reply" not in without["gmail"] and "forward" in without["gmail"]
