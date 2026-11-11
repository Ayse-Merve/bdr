"""Tests for assign_persona_keys.py. Run from the repo root: python3 -m unittest
Synthetic records only: no real lead data in this file."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("apk", Path(__file__).with_name("assign_persona_keys.py"))
apk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apk)

CFG = apk.Config()


def lead(**kw):
    rec = {"Id": "00Q000000000001AAA", "Email": "j.doe@example-gov.nl", "Company": "", "Title": None,
           "CountryCode": None, "Status": "Information Qualified (IQL)"}
    rec.update(kw)
    return rec


def run(rec, opps=None, decisions=None):
    return apk.classify_lead(rec, opps or {}, decisions or {}, CFG)


def persona(title, email="j.doe@gemeente-x.nl"):
    ei = apk.email_info({"Email": email}, CFG)
    return apk.resolve_persona(title, ei, CFG)[0]


class Keys(unittest.TestCase):
    def test_seventy_keys(self):
        keys = list(apk.all_keys())
        self.assertEqual(len(keys), 90)
        self.assertEqual(len(set(keys)), 90)
        self.assertTrue(all(apk.KEY_RE.match(k) for k in keys))
        self.assertIn("NL-GEN", keys)
        self.assertNotIn("NL-GEN-O", keys)


class Persona(unittest.TestCase):
    def test_elected(self):
        for t in ["Raadslid", "Wethouder Participatie", "Bürgermeisterin", "Councillor", "Mayor", "Schepen",
                  "Adjointe à la démocratie participative", "Maire", "Byrådsmedlem", "Concejal", "Raadsgriffier"]:
            self.assertEqual(persona(t), "POL", t)

    def test_engagement(self):
        for t in ["Communicatieadviseur", "Adviseur burgerparticipatie", "Leiterin Bürgerbeteiligung",
                  "Chargée de concertation", "Head of Engagement and Consultation", "Community Engagement Director",
                  "Programmamanager Omgevingswet", "Specialkonsulent, borgerinddragelse", "Directeur de la communication"]:
            self.assertEqual(persona(t), "ENG", t)

    def test_director_is_the_fallback(self):
        for t in ["City Manager", "Beleidsadviseur", "Directrice Générale des Services (DGS)", "Projectmanager",
                  "Depute Chief Executive", "Directeur adjoint", "Senior Transportation Officer", "Gemeentesecretaris",
                  "Secrétaire générale", "Assistant City Manager"]:
            self.assertEqual(persona(t), "DIR", t)

    def test_general(self):
        for t in ["Intern", "Stagiair communicatie", "Adjoint administratif", "Employée d'administration",
                  "Secretary", "Werkstudentin Partizipation"]:
            self.assertEqual(persona(t), "GEN", t)

    def test_no_title(self):
        self.assertEqual(persona(None, "someone@gmail.com"), "GEN")
        self.assertEqual(persona(None, "j.doe@gemeente-x.nl"), "DIR")
        self.assertEqual(persona("Overig", "j.doe@gemeente-x.nl"), "DIR")
        self.assertEqual(persona("Wethouder", "info@gemeente-x.nl"), "GEN")  # shared inbox wins

    def test_resident_is_excluded(self):
        r = run(lead(Title="Inwoner", Company="Gemeente Voorbeeld", CountryCode="NL"))
        self.assertEqual(r["status"], "excluded")


class Market(unittest.TestCase):
    def gov(self, **kw):
        base = dict(Company_type__c="Local government", Email="j.doe@stad-x.example")
        base.update(kw)
        return run(lead(**base))

    def test_country_map(self):
        self.assertEqual(self.gov(CountryCode="SE", Company="Malmö stad")["market"], "NORDICS")
        self.assertEqual(self.gov(CountryCode="IT", Company="Comune di Bergamo")["market"], "IT")
        self.assertEqual(self.gov(CountryCode="MX", Company="Municipio de Querétaro")["market"], "ES")
        self.assertEqual(self.gov(CountryCode="CL", Company="Municipalidad de Providencia")["market"], "ES")
        self.assertEqual(self.gov(CountryCode="AU", Company="City of Sydney")["market"], "NAM")
        self.assertEqual(self.gov(CountryCode="UK", Company="Anytown Council")["market"], "UKI")
        self.assertEqual(self.gov(CountryCode="LU", Company="Ville de Luxembourg")["market"], "FR")

    def test_belgium_split(self):
        self.assertEqual(self.gov(CountryCode="BE", PostalCode="9000", Company="Lokaal bestuur X")["market"], "BE")
        self.assertEqual(self.gov(CountryCode="BE", PostalCode="4000", Company="Ville X")["market"], "FR")
        self.assertEqual(self.gov(CountryCode="BE", StateCode="BEWLG", Company="X")["market"], "FR")
        self.assertEqual(self.gov(CountryCode="BE", StateCode="BEVAN", Company="X")["market"], "BE")
        self.assertEqual(self.gov(CountryCode="BE", Company="Commune de X")["market"], "FR")
        self.assertEqual(self.gov(CountryCode="BE", Company="X")["status"], "review")

    def test_canada_and_switzerland(self):
        self.assertEqual(self.gov(CountryCode="CA", StateCode="QC", Company="Ville de X")["market"], "FR")
        self.assertEqual(self.gov(CountryCode="CA", StateCode="ON", Company="City of X")["market"], "NAM")
        self.assertEqual(self.gov(CountryCode="CH", StateCode="CHGE", Company="Ville de X")["market"], "FR")
        self.assertEqual(self.gov(CountryCode="CH", StateCode="CHZU", Company="Stadt X")["market"], "DACH")

    def test_name_language_sanity_check(self):
        r = self.gov(CountryCode="BY", Company="Gemeente Voorbeeld", Email="someone@gmail.com")
        self.assertEqual(r["status"], "review")


class Size(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(apk.tier_for(29999, "NL", CFG), "S")
        self.assertEqual(apk.tier_for(30000, "NL", CFG), "O")
        self.assertEqual(apk.tier_for(250000, "NL", CFG), "W")
        self.assertEqual(apk.tier_for(99999, "UKI", CFG), "S")
        self.assertEqual(apk.tier_for(19999, "DACH", CFG), "S")
        self.assertEqual(apk.tier_for(100000, "DACH", CFG), "W")

    def test_form_band_only_when_decisive(self):
        self.assertEqual(apk.band_tier("30,001 - 100,000", "NL", CFG), "O")
        self.assertIsNone(apk.band_tier("30,001 - 100,000", "NAM", CFG))  # straddles 50k
        self.assertEqual(apk.band_tier("&gt;250,000", "NAM", CFG), "W")

    def test_regional_body_is_whales(self):
        r = run(lead(Company="Anyshire County Council", CountryCode="UK", Company_type__c="Local government",
                     Title="Head of Policy", Email="j.doe@anyshire.example"))
        self.assertEqual(r["key"], "UKI-DIR-W")

    def test_unknown_size_gets_octopus(self):
        r = run(lead(Company="Gemeente Nergenshuizen", CountryCode="NL", Company_type__c="Local government",
                     Title="Wethouder", Email="j.doe@nergenshuizen.example"))
        self.assertEqual(r["key"], "NL-POL-O")


class Exclusions(unittest.TestCase):
    ACCT = {"Name": "Gemeente Voorbeeld", "accountstatus__c": "Prospect", "RecordType": {"DeveloperName": "Customer"},
            "Organization_Type__c": "Local government"}

    def with_acct(self, acct=None, opps=None, **kw):
        base = dict(Company="Gemeente Voorbeeld", CountryCode="NL", Email="j.doe@voorbeeld.nl", Title="Beleidsadviseur",
                    Matched_Account__c="001000000000001AAA", Matched_Account__r=dict(self.ACCT, **(acct or {})))
        base.update(kw)
        return run(lead(**base), {"001000000000001AAA": opps} if opps else {})

    def test_prospect_account_is_keyed(self):
        self.assertEqual(self.with_acct()["status"], "keyed")

    def test_relationships(self):
        self.assertEqual(self.with_acct({"accountstatus__c": "Customer"})["status"], "excluded")
        self.assertEqual(self.with_acct({"RecordType": {"DeveloperName": "Current_Client"}})["status"], "excluded")
        self.assertEqual(self.with_acct({"RecordType": {"DeveloperName": "Customer_Churned"}})["status"], "excluded")
        self.assertEqual(self.with_acct(opps=[{"IsClosed": False, "IsWon": False}])["status"], "excluded")
        self.assertEqual(self.with_acct(opps=[{"IsClosed": True, "IsWon": False}])["status"], "excluded")

    def test_personal_email_ignores_the_match(self):
        r = self.with_acct({"accountstatus__c": "Customer"}, Email="someone@gmail.com", Company="Gemeente Elders")
        self.assertNotEqual(r["excluded_reason"] or "", "client account (Gemeente Voorbeeld)")

    def test_lookalike_account_goes_to_review(self):
        r = self.with_acct({"Name": "Gemeente Enkhuizen"}, Company="Gemeente Huizen", Email="j.doe@huizen.nl")
        self.assertEqual(r["status"], "review")

    def test_domain_match_with_another_government_named(self):
        r = self.with_acct({"Name": "EDF", "Organization_Type__c": None}, Company="Ville de Bouscat",
                           Email="j.doe@edf.fr", CountryCode="FR")
        self.assertEqual(r["status"], "review")

    def test_intake(self):
        self.assertEqual(run(lead(Email="x@govocal.com"))["status"], "excluded")
        self.assertEqual(run(lead(Company="TESTNLORG", Email="a+b@gmail.com"))["status"], "excluded")
        self.assertEqual(run(lead(Status="Spam", Company="google"))["status"], "excluded")
        self.assertEqual(run(lead(Company="Teston Parish Council", CountryCode="UK", Email="clerk@teston.example",
                                  Company_type__c="Local government"))["status"], "keyed")

    def test_org_types(self):
        self.assertEqual(run(lead(Company="Adviesbureau X", Organization_type__c="Consultant", CountryCode="NL"))["status"],
                         "excluded")
        self.assertEqual(run(lead(Company="Uni X", Email="a@student.uni-x.be", CountryCode="BE"))["status"], "excluded")
        self.assertEqual(run(lead(Company="[[Unknown]]", Email="a@gmail.com", CountryCode="FR",
                                  Organization_type__c="Local government"))["status"], "excluded")

    def test_elected_title_outranks_org_type(self):
        r = run(lead(Company="Hogeschool X", Organization_type__c="Education or research", Title="Raadslid",
                     CountryCode="NL", Email="someone@gmail.com"))
        self.assertEqual(r["key"], "NL-POL-O")


class SizeEstimate(unittest.TestCase):
    REC = dict(Company="Gemeente Nergenshuizen", CountryCode="NL", Company_type__c="Local government",
               Title="Beleidsadviseur", Email="j.doe@nergenshuizen.example")

    def test_no_population_asks_for_an_estimate(self):
        r = run(lead(**self.REC))
        self.assertEqual(r["key"], "NL-DIR-O")
        self.assertIn("size_check", r)

    def test_estimate_sets_the_size(self):
        rec = lead(**self.REC)
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"population": 12000, "population_note": "estimate"}}}
        r = run(rec, decisions=dec)
        self.assertEqual(r["key"], "NL-DIR-S")
        self.assertNotIn("size_check", r)

    def test_general_needs_no_size(self):
        r = run(lead(**dict(self.REC, Title=None, Email="someone@gmail.com")))
        self.assertEqual(r["key"], "NL-GEN")
        self.assertNotIn("size_check", r)

    def test_decision_lines_add_up(self):
        import json, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"id": "00Q1", "decision": {"account": "ignore"}}) + "\n")
            fh.write(json.dumps({"id": "00Q1", "decision": {"population": 40000}}) + "\n")
        try:
            self.assertEqual(apk.load_decisions(fh.name)["00Q1"]["decision"], {"account": "ignore", "population": 40000})
        finally:
            os.unlink(fh.name)


class TitleLookup(unittest.TestCase):
    REC = dict(Company="Gemeente Nergenshuizen", CountryCode="NL", Company_type__c="Local government",
               Email="c.janssen@nergenshuizen.example", Inhabitants__c="<10,000")

    def test_no_title_asks_for_a_lookup(self):
        r = run(lead(**self.REC))
        self.assertEqual(r["key"], "NL-DIR-S")
        self.assertIn("title_check", r)

    def test_found_role_sets_the_persona(self):
        rec = lead(**self.REC)
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"title": "Communicatieadviseur", "title_source": "gemeente site"}}}
        r = run(rec, decisions=dec)
        self.assertEqual(r["key"], "NL-ENG-S")
        self.assertNotIn("title_check", r)
        self.assertTrue(r["basis"]["persona"].startswith("researched title"))

    def test_councillor_on_gmail(self):
        rec = lead(**dict(self.REC, Email="someone@gmail.com"))
        self.assertEqual(run(rec)["key"], "NL-GEN")
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"title": "Raadslid"}}}
        self.assertEqual(run(rec, decisions=dec)["key"], "NL-POL-S")

    def test_nothing_found_keeps_the_fallback(self):
        rec = lead(**self.REC)
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"title": "", "title_source": "not found"}}}
        r = run(rec, decisions=dec)
        self.assertEqual(r["key"], "NL-DIR-S")
        self.assertNotIn("title_check", r)

    def test_team_inbox_is_not_looked_up(self):
        r = run(lead(**dict(self.REC, Email="info@nergenshuizen.example")))
        self.assertEqual(r["key"], "NL-GEN")
        self.assertNotIn("title_check", r)

    def test_title_on_record_wins(self):
        rec = lead(**dict(self.REC, Title="Wethouder"))
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"title": "Communicatieadviseur"}}}
        self.assertEqual(run(rec, decisions=dec)["key"], "NL-POL-S")


class Decisions(unittest.TestCase):
    def test_decision_closes_the_review(self):
        rec = lead(Company="Gemeente Huizen", CountryCode="NL", Email="j.doe@huizen.nl", Title="Wethouder",
                   Matched_Account__c="001000000000002AAA",
                   Matched_Account__r={"Name": "Gemeente Enkhuizen", "accountstatus__c": "Prospect",
                                       "RecordType": {"DeveloperName": "Customer"}})
        self.assertEqual(run(rec)["status"], "review")
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"account": "ignore", "org": "government"}}}
        r = run(rec, decisions=dec)
        self.assertEqual(r["status"], "keyed")
        self.assertEqual(r["persona"], "POL")

    def test_exclude_decision(self):
        rec = lead(Company="Zaanse corporaties", CountryCode="NL")
        dec = {rec["Id"]: {"id": rec["Id"], "decision": {"exclude": "housing association, not government"}}}
        self.assertEqual(run(rec, decisions=dec)["status"], "excluded")


if __name__ == "__main__":
    unittest.main()
