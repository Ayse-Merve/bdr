import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bdr import batch  # noqa: E402


def test_render_greeting():
    assert batch.render("Hi {{Recipient.FirstName}},\n\nText", "Anna", "") == "Hi Anna,\n\nText"
    assert batch.render("Hi {{Recipient.FirstName}},", "", "") == "Hi,"
    assert batch.render("Guten Tag {{Recipient.FirstName}} {{Recipient.LastName}},", "Jonas", "Becker") == "Guten Tag Jonas Becker,"
    assert batch.render("Guten Tag {{Recipient.FirstName}} {{Recipient.LastName}},", "", "") == "Guten Tag,"


def test_clean_name():
    assert batch.clean_name("J?r?me") == ""
    assert batch.clean_name("BAPTISTE") == "Baptiste"
    assert batch.clean_name(" Søren ") == "Søren"


def test_build(tmp_path):
    plan = {"rows": [
        {"id": "L1", "status": "keyed", "key": "NORDICS-DIR-O", "org_country": "DK"},
        {"id": "L2", "status": "keyed", "key": "NORDICS-DIR-O", "org_country": "SE"},
        {"id": "L3", "status": "keyed", "key": "DACH-GEN", "org_country": "DE"},
        {"id": "L4", "status": "excluded", "key": None, "excluded_reason": "not a government body (company)"}]}
    leads = [{"Id": "L1", "Email": "m@kommune.dk", "FirstName": "Mette", "LastName": "Hansen"},
             {"Id": "L2", "Email": "e@kommun.se", "FirstName": "Erik", "LastName": "Lund"},
             {"Id": "L3", "Email": "j@stadt.de", "FirstName": "Jonas", "LastName": "Becker"},
             {"Id": "L4", "Email": "x@acme.com", "FirstName": "X", "LastName": "Y"}]
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "leads.json").write_text(json.dumps(leads))
    s = batch.build(tmp_path / "plan.json", [tmp_path / "leads.json"], tmp_path / "out")
    assert s["keyed"] == 3 and s["no_key"] == 1
    rows = list(csv.DictReader((tmp_path / "out/pardot-import.csv").open(encoding="utf-8-sig")))
    by = {r["Salesforce Lead ID"]: r for r in rows}
    assert by["L1"]["Language"] == "Danish" and by["L1"]["Nurture track message"].startswith("Hej Mette,")
    assert by["L2"]["Language"] == "English" and by["L2"]["Nurture track message"].startswith("Hi Erik,")
    assert by["L3"]["Nurture track message"].startswith("Guten Tag Jonas Becker,")
    assert "{{" not in "".join(r["Nurture track message"] + r["Nurture track subject"] for r in rows)
    assert by["L1"]["Nurture track message (HTML)"].startswith("<p>Hej Mette,</p>")
