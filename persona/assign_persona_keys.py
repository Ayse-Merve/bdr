#!/usr/bin/env python3
"""Assign Go Vocal persona keys to Salesforce Leads.

A persona key tells Pardot Engagement Studio which of the 70 nurture emails a lead gets:
<MARKET>-<PERSONA>-<SIZE> (e.g. NL-ENG-O), or <MARKET>-GEN for the General email.
Every list and threshold is in config.json next to this file. Nothing here calls
Salesforce: Claude runs the queries and the writes and hands this script the JSON.

  classify  leads JSON (+ opportunities, + review decisions) -> plan JSON
  record    plan + read-back JSON -> state/ write log, undo CSV, run file, run-log line
  keys      the 70 valid keys, one per line (the Persona_Key__c picklist values)

Standard library only.
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import unicodedata
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")
MARKETS = ["NAM", "UKI", "NL", "BE", "FR", "DACH", "NORDICS"]
ROLE_PERSONAS = ["ENG", "DIR", "POL"]
SIZES = ["S", "O", "W"]
KEY_RE = re.compile(r"^(NAM|UKI|NL|BE|FR|DACH|NORDICS)-((ENG|DIR|POL)-(S|O|W)|GEN)$")

# Domain labels stripped from the right before taking the organisation part of a domain.
SUFFIX_LABELS = set("""com org net edu gov mil int info biz eu co ac go gouv gv gob govt nhs
nl be fr de at ch li dk se no fi is gl fo uk ie us ca au nz it es pt lu pl cz gr ro cl mx ar br
za ke hk sg in jp cn tw kr ru ua by al hr si sk hu bg rs ba me mk ee lv lt mt cy tr il ae sa eg ma
tn dz sn ci cm cd cg ml bf ne bj tg gn ga mg ht mr td cf dj km bi pe ec uy py bo ve cr pa gt hn
sv ni do cu pr tt jm bs bb ph my id th vn pk bd lk np ng gh tz ug et rw zm zw mz ao na bw
al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc
nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc
ab bc mb nb nl ns on pe qc sk nt nu yt
nsw vic qld sa tas act""".split())
DOMAIN_PREFIXES = ["gemeente", "stadt", "gemeinde", "villede", "ville", "mairie", "commune", "kommune",
                   "kommun", "cityof", "townof", "villageof", "countyof", "municipalidad", "municipio",
                   "comune", "stad"]
NAME_STOPWORDS = set("""gemeente gemeentebestuur city of the council councils borough town village municipality
municipal commune ville de du des la le les stad stadt gemeinde kommune kommuneqarfik kommun district
metropolitan london lb royal and en und et administration communale government regional provincie
province region mairie county cc dc bc mbc van der den het op aan upon on in im am an inc gov
ayuntamiento municipalidad comune di del della city's township parish lokaal bestuur ocmw cpas""".split())
LANGUAGE_MARKETS = {"dutch": {"NL", "BE"}, "french": {"FR"}, "german": {"DACH"}, "nordic": {"NORDICS"}}


# ---------------------------------------------------------------- text helpers

def norm(s):
    """Lower case, accents off, anything but letters and digits -> single spaces."""
    s = html.unescape(str(s or "")).lower()
    for a, b in (("æ", "ae"), ("ø", "o"), ("å", "a"), ("ß", "ss"), ("œ", "oe")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def any_match(patterns, text):
    for p in patterns:
        if re.search(p, text):
            return p
    return None


def sig_tokens(name):
    return {t for t in norm(name).split() if len(t) >= 3 and t not in NAME_STOPWORDS}


def domain_base(domain):
    labels = [l for l in (domain or "").lower().split(".") if l]
    while len(labels) > 1 and labels[-1] in SUFFIX_LABELS:
        labels.pop()
    base = re.sub(r"[^a-z]", "", re.sub(r"\d+", "", labels[-1] if labels else ""))
    for p in DOMAIN_PREFIXES:
        if base.startswith(p) and len(base) > len(p) + 2:
            return base[len(p):]
    return base


def account_trust(company, org_domain_base, account_name, gov_patterns):
    """Is the matched account the lead's organisation? Exact tokens only: 'huizen' must not
    match 'Enkhuizen'. A matching email domain is enough, unless the company field names a
    different government body (lead at edf.fr who wrote 'Ville de Bouscat')."""
    company_sig, acct_sig = sig_tokens(company), sig_tokens(account_name)
    if company_sig & acct_sig:
        return True
    if not domain_matches(org_domain_base, account_name, acct_sig):
        return False
    return not (company_sig and any_match(gov_patterns, norm(company)))


def domain_matches(org_domain_base, account_name, acct_sig):
    if org_domain_base:
        concat_sig = "".join(t for t in norm(account_name).split() if t in acct_sig)
        concat_all = norm(account_name).replace(" ", "")
        if org_domain_base in (concat_sig, concat_all) or org_domain_base in acct_sig:
            return True
        if len(concat_sig) >= 5 and (org_domain_base.startswith(concat_sig) or org_domain_base.endswith(concat_sig)):
            return True
    return False


def get(rec, path):
    cur = rec
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


# ---------------------------------------------------------------- config and input

class Config:
    def __init__(self, path=CONFIG):
        c = json.loads(Path(path).read_text())
        self.markets, self.bands, self.personas, self.elig = c["markets"], c["size"], c["personas"], c["eligibility"]
        self.country_names = {norm(k): v for k, v in self.markets["country_names"].items() if not k.startswith("_")}
        self.cctld = {k: v for k, v in self.markets["cctld"].items() if not k.startswith("_")}
        self.no_title = {norm(v) for v in self.personas["not_a_title"]["values"]}
        self.no_org = {norm(v) for v in self.elig["no_organisation_companies"]["values"]}
        ot = self.elig["org_types"]
        self.org_gov = {norm(v) for v in ot["government"]}
        self.org_public = {norm(v) for v in ot["public_institution"]}
        self.org_excluded = {norm(k): v for k, v in ot["excluded"].items()}
        self.inh_bands = {norm(k): v for k, v in self.bands["inhabitants_bands"].items() if not k.startswith("_")}
        self.regional_types = {norm(v) for v in self.bands["regional_bodies"]["org_types"]}


def load_records(paths):
    out = []
    for p in paths or []:
        data = json.loads(Path(p).read_text())
        if isinstance(data, dict):
            data = data.get("records", [])
        out.extend(data)
    return out


def load_decisions(path):
    """Claude's decisions, one JSON object per line. Lines for the same lead add up; a later value wins."""
    dec = {}
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                dec.setdefault(d["id"], {"id": d["id"], "decision": {}})["decision"].update(d.get("decision", {}))
    return dec


# ---------------------------------------------------------------- one dimension at a time

def email_info(rec, cfg):
    email = (rec.get("Email") or "").strip().lower()
    local, _, domain = email.partition("@")
    pe = cfg.personas["personal_email_domains"]
    personal = (domain in pe["exact"] or any(domain.startswith(p) for p in pe["prefixes"])
                or rec.get("EmailDomain__Personal_Email_Domain__c") == "Yes")
    sh = cfg.personas["shared_inbox_locals"]
    local_clean = re.sub(r"[\d._\-+]", "", local)
    shared = bool(local) and (local_clean in sh["values"] or any(local_clean.startswith(p) for p in sh["prefixes"]))
    return {"local": local, "domain": domain, "personal": personal, "shared": shared,
            "base": None if personal or not domain else domain_base(domain)}


def country_code(value, cfg):
    if not value:
        return None
    v = str(value).strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return cfg.country_names.get(norm(v))


def tld_country(domain, cfg):
    if not domain:
        return None
    last = domain.split(".")[-1]
    return "UK" if last == "uk" else cfg.cctld.get(last)


def country_entry(cc, cfg):
    return cfg.markets["countries"].get(cc) or cfg.markets["default_country"]


def name_language(name, cfg):
    text = " " + norm(name) + " "
    marks = cfg.markets["name_language_markers"]
    found = [lang for lang in ("dutch", "french", "german", "italian", "nordic")
             if any(" " + norm(m) + " " in text for m in marks.get(lang, []))]
    return found[0] if len(found) == 1 else None


def in_ranges(n, ranges):
    return any(lo <= n <= hi for lo, hi in ranges)


def resolve_split(entry, ctx, cfg):
    """BE, CH and CA need a second look: which language does the organisation work in?
    Returns (market, bands, basis) or (None, None, review question)."""
    sp = cfg.markets["splits"][entry["split"]]
    states = [s for s in (ctx["acct_state"], ctx["lead_state"]) if s]
    names = [n for n in (ctx["account_name"], ctx["company"]) if n]
    lang = next((name_language(n, cfg) for n in names if name_language(n, cfg)), None)
    if entry["split"] == "CA":
        if any(s in sp["french_states"] for s in states) or lang == "french":
            return sp["french"]["market"], sp["french"]["bands"], "Quebec / French-speaking"
        return entry["market"], entry["bands"], "Canada outside Quebec"
    if entry["split"] == "CH":
        if any(s in sp["french_states"] for s in states) or lang == "french":
            return sp["french"]["market"], sp["french"]["bands"], "French-speaking Switzerland"
        if any(s in sp["italian_states"] for s in states) or lang == "italian":
            return sp["italian"]["market"], sp["italian"]["bands"], "Ticino (Italian-speaking): English email"
        return entry["market"], entry["bands"], "German-speaking Switzerland"
    # Belgium
    if any(s in sp["dutch_states"] for s in states):
        return entry["market"], entry["bands"], "Flanders (province)"
    if any(s in sp["french_states"] for s in states):
        return sp["french"]["market"], sp["french"]["bands"], "Wallonia (province)"
    brussels = any(s in sp["brussels_states"] for s in states)
    for pc in (ctx["acct_postal"], ctx["lead_postal"]):
        m = re.match(r"\s*(\d{4})", str(pc or ""))
        if m:
            n = int(m.group(1))
            if in_ranges(n, sp["dutch_postal_ranges"]):
                return entry["market"], entry["bands"], f"Flanders (postcode {n})"
            if in_ranges(n, sp["french_postal_ranges"]):
                return sp["french"]["market"], sp["french"]["bands"], f"Wallonia (postcode {n})"
            if in_ranges(n, sp["brussels_postal_ranges"]):
                brussels = True
    if lang == "dutch":
        return entry["market"], entry["bands"], "Dutch organisation name" + (" (Brussels)" if brussels else "")
    if lang == "french":
        return sp["french"]["market"], sp["french"]["bands"], "French organisation name" + (" (Brussels)" if brussels else "")
    return None, None, "Belgian lead: Dutch-speaking (BE) or French-speaking (FR)? Nothing on the record says which."


def resolve_market(rec, ei, acct, trusted, cfg, forced_cc=None):
    """(market, bands, country, basis), or (None, None, country, review question)."""
    lead_cc = forced_cc or country_code(rec.get("CountryCode"), cfg) or country_code(rec.get("Country"), cfg)
    acct_cc = (country_code(acct.get("BillingCountryCode"), cfg) or country_code(acct.get("BillingCountry"), cfg)) \
        if trusted else None
    tld_cc = tld_country(ei["domain"], cfg) if not ei["personal"] else None
    notes = []
    if forced_cc:
        cc, src = forced_cc, "review decision"
    elif acct_cc:
        cc, src = acct_cc, "matched account"
        if lead_cc and country_entry(lead_cc, cfg)["market"] != country_entry(acct_cc, cfg)["market"]:
            notes.append(f"lead says {lead_cc}, account says {acct_cc}: account wins")
    elif lead_cc:
        cc, src = lead_cc, "lead country"
        if tld_cc and country_entry(tld_cc, cfg)["market"] != country_entry(lead_cc, cfg)["market"]:
            return None, None, None, (f"Lead country {lead_cc} but email domain .{ei['domain'].split('.')[-1]} "
                                      f"points to {tld_cc}. Which is the organisation's country?")
    elif tld_cc:
        cc, src = tld_cc, "email domain"
    else:
        return None, None, None, "No country on the lead, its matched account or its email domain."
    entry = country_entry(cc, cfg)
    market, bands, why = entry["market"], entry["bands"], ""
    if entry.get("split"):
        ctx = {"acct_state": acct.get("BillingStateCode") if trusted else None,
               "acct_postal": acct.get("BillingPostalCode") if trusted else None,
               "lead_state": rec.get("StateCode"), "lead_postal": rec.get("PostalCode"),
               "account_name": acct.get("Name") if trusted else None, "company": rec.get("Company")}
        market, bands, why = resolve_split(entry, ctx, cfg)
        if market is None:
            return None, None, cc, why
    lang = name_language(rec.get("Company"), cfg)
    if not trusted and not forced_cc and lang in LANGUAGE_MARKETS and market not in LANGUAGE_MARKETS[lang]:
        return None, None, cc, (f"Country {cc} gives the {market} email, but the organisation name "
                                f"'{rec.get('Company')}' reads {lang}. Which country is the organisation in?")
    return market, bands, cc, f"{src} {cc}" + (f": {why}" if why else "") + (f" ({'; '.join(notes)})" if notes else "")


def resolve_org(rec, acct, trusted, ei, cfg):
    """government | public_institution | excluded:<reason> | unknown, plus the basis and a review question.
    Any government type on the lead or its account wins; the name and domain only decide when no type is
    set, or flag a conflict when every type set says 'not government'."""
    if ei["domain"] and any_match(cfg.elig["org_types"]["education_domain_patterns"], ei["domain"]):
        return "excluded:education or research", f"education email domain ({ei['domain']})", None
    values = []
    if trusted:
        values += [("account org type", acct.get("Organization_Type__c")), ("account company type", acct.get("Company_Type__c")),
                   ("account customer type", acct.get("Customer_Type_L1__c"))]
    values += [("lead company type", rec.get("Company_type__c")), ("lead org type", rec.get("Organization_type__c"))]
    looks_gov = None
    if rec.get("Company") and any_match(cfg.elig["government_name_patterns"], norm(rec["Company"])):
        looks_gov = "government name pattern"
    elif ei["domain"] and not ei["personal"] and any_match(cfg.elig["government_domain_patterns"], ei["domain"]):
        looks_gov = "government email domain"
    known = []
    for src, v in values:
        n = norm(v)
        if n in cfg.org_gov:
            known.append(("government", src, v))
        elif n in cfg.org_public:
            known.append(("public_institution", src, v))
        elif n in cfg.org_excluded:
            known.append(("excluded:" + cfg.org_excluded[n], src, v))
    for cls in ("government", "public_institution"):
        hit = next((k for k in known if k[0] == cls), None)
        if hit:
            return cls, f"{hit[1]}: {hit[2]}", None
    if known:
        cls, src, v = known[0]
        if looks_gov:
            return "unknown", f"{src}: {v}", (f"Org type says '{v}' but {looks_gov} ({rec.get('Company') or ei['domain']}). "
                                              "Is it a government body?")
        return cls, f"{src}: {v}", None
    if looks_gov:
        return "government", looks_gov, None
    if trusted and any_match(cfg.elig["government_name_patterns"], norm(acct.get("Name"))):
        return "government", f"matched account name ({acct.get('Name')})", None
    return "unknown", "no org type on the record", None


def tier_for(pop, bands_key, cfg):
    b = cfg.bands["bands"][bands_key]
    if pop < b["shrimps_below"]:
        return "S"
    return "W" if pop >= b["whales_from"] else "O"


def band_tier(band, bands_key, cfg):
    rng = cfg.inh_bands.get(norm(band))
    if not rng:
        return None
    lo, hi = tier_for(rng[0], bands_key, cfg), tier_for(rng[1], bands_key, cfg)
    return lo if lo == hi else None


UNKNOWN_SIZE = "size unknown: Octopus email"


def resolve_size(rec, acct, trusted, bands_key, cfg, estimate=None, note=None):
    reg = cfg.bands["regional_bodies"]
    names = [n for n in ((acct.get("Name") if trusted else None), rec.get("Company")) if n]
    types = [norm(v) for v in ((acct.get("Organization_Type__c") if trusted else None),
                               rec.get("Company_type__c"), rec.get("Organization_type__c")) if v]
    if any(t in cfg.regional_types for t in types):
        return "W", "regional / national body: Whales"
    for n in names:
        if any_match(reg["name_patterns"], norm(n)):
            return "W", f"regional body by name ({n}): Whales"
    tag = f"{bands_key} bands" + (", provisional" if cfg.bands["bands"][bands_key]["status"] != "locked" else "")
    if trusted:
        for f in ("Population__c", "Inhabitants_in_numbers__c"):
            v = acct.get(f)
            if isinstance(v, (int, float)) and v > 0:
                return tier_for(v, bands_key, cfg), f"account {f}: {int(v):,} ({tag})"
        t = band_tier(acct.get("Inhabitants__c"), bands_key, cfg)
        if t:
            return t, f"account Inhabitants__c {html.unescape(acct.get('Inhabitants__c'))} ({tag})"
    t = band_tier(rec.get("Inhabitants__c"), bands_key, cfg)
    if t:
        return t, f"form answer {html.unescape(rec.get('Inhabitants__c'))} ({tag})"
    if isinstance(estimate, (int, float)) and estimate > 0:
        return tier_for(estimate, bands_key, cfg), \
            f"Claude's population estimate {int(estimate):,}" + (f", {note}" if note else "") + f" ({tag})"
    return "O", UNKNOWN_SIZE


def has_title(title, cfg):
    t = norm(title)
    return bool(t) and t not in cfg.no_title


def resolve_persona(title, ei, cfg):
    """(persona, basis, private_person)."""
    t = norm(title)
    pp = cfg.personas
    if t and any_match(pp["private_person"]["patterns"], t):
        return None, f"title '{title}' is a resident, not staff", True
    if ei["shared"]:
        return "GEN", f"shared inbox ({ei['local']}@)", False
    if t and t not in cfg.no_title:
        if any_match(pp["junior"], t):
            return "GEN", f"title '{title}': junior or support role", False
        if any_match(pp["elected"], t):
            return "POL", f"title '{title}': elected or council office", False
        if any_match(pp["engagement"], t):
            return "ENG", f"title '{title}': engagement, participation or communications", False
        return "DIR", f"title '{title}': no engagement or elected keyword, so the Director email", False
    if ei["personal"]:
        return "GEN", "no title and a personal email address", False
    return "DIR", "no title, named address at the organisation: Director email", False


# ---------------------------------------------------------------- one lead

def classify_lead(rec, opps_by_acct, decisions, cfg):
    ei = email_info(rec, cfg)
    acct = rec.get("Matched_Account__r") or {}
    acct_id = rec.get("Matched_Account__c")
    dec = (decisions.get(rec.get("Id")) or {}).get("decision", {})
    row = {"id": rec.get("Id"), "company": rec.get("Company"), "title": rec.get("Title"),
           "country": rec.get("CountryCode") or rec.get("Country"), "email_domain": ei["domain"],
           "status": None, "key": None, "market": None, "persona": None, "size": None,
           "basis": {}, "review": [], "excluded_reason": None}

    def exclude(reason):
        row["status"], row["excluded_reason"] = "excluded", reason
        return row

    # 1. intake exclusions
    intake = cfg.elig["intake"]
    company_n = norm(rec.get("Company"))
    if ei["domain"] in intake["internal_domains"]:
        return exclude("internal (@" + ei["domain"] + ")")
    if any_match(intake["test_company_patterns"], company_n) or company_n in {norm(x) for x in intake["test_company_names"]} \
            or any_match(intake["test_domain_patterns"], ei["domain"]):
        return exclude("test record")
    if rec.get("Status") in intake["spam_statuses"]:
        return exclude("marked Spam in Salesforce")
    if dec.get("exclude"):
        return exclude("review decision: " + dec["exclude"])

    # 2. is the matched account the lead's organisation?
    trusted = False
    if acct_id and acct:
        if dec.get("account") in ("trust", "ignore"):
            trusted = dec["account"] == "trust"
            row["basis"]["account"] = f"review decision: {dec['account']} {acct.get('Name')}"
        elif ei["personal"]:
            row["basis"]["account"] = f"ignored {acct.get('Name')}: personal email (the matcher is unreliable there)"
        elif account_trust(rec.get("Company"), ei["base"], acct.get("Name"), cfg.elig["government_name_patterns"]):
            trusted = True
            row["basis"]["account"] = f"matched {acct.get('Name')}"
        else:
            row["review"].append({"on": "account", "question": f"Matched account '{acct.get('Name')}' does not look like "
                                  f"'{rec.get('Company')}' ({ei['domain']}). Is it the lead's organisation?"})

    # 3. clients, deals, churned and partners never enter nurture (scoring rulebook 5.2, 5.4)
    if trusted:
        rel = cfg.elig["relationships"]
        rt = get(acct, "RecordType.DeveloperName")
        if rel["client"] and (acct.get("accountstatus__c") == "Customer" or rt == "Current_Client"):
            return exclude(f"client account ({acct.get('Name')})")
        if rel["churned"] and rt == "Customer_Churned":
            return exclude(f"churned client ({acct.get('Name')})")
        if rel["partner"] and rt == "Partner":
            return exclude(f"partner account ({acct.get('Name')})")
        opps = opps_by_acct.get(acct_id) or opps_by_acct.get((acct_id or "")[:15]) or []
        if rel["open_opportunity"] and any(not o.get("IsClosed") for o in opps):
            return exclude(f"open opportunity on {acct.get('Name')}")
        if rel["client"] and any(o.get("IsWon") for o in opps):
            return exclude(f"won deal on {acct.get('Name')} (client history)")
        if rel["closed_lost"] and any(o.get("IsClosed") and not o.get("IsWon") for o in opps):
            return exclude(f"closed-lost deal on {acct.get('Name')}")

    # 4. persona: a resident is not a prospect, and an elected title outranks the org type.
    #    No title on the record: use the role Claude found by looking the person up, if any.
    title, researched = rec.get("Title"), False
    if not has_title(title, cfg) and dec.get("title"):
        title, researched = dec["title"], True
    persona, p_basis, private = resolve_persona(title, ei, cfg)
    if researched:
        p_basis = "researched " + p_basis + (f" ({dec['title_source']})" if dec.get("title_source") else "")
    if private:
        return exclude(p_basis)

    # 5. organisation
    elected_override = persona == "POL" and cfg.elig["elected_title_overrides_org_type"]
    if ei["personal"] and (not company_n or company_n in cfg.no_org) and not elected_override and not dec.get("org"):
        return exclude("no organisation we can verify (personal email, no organisation named)")
    org = dec.get("org")
    if org:
        org_basis, org_q = "review decision", None
        if org.startswith("exclude:"):
            org = "excluded:" + org.split(":", 1)[1]
    else:
        org, org_basis, org_q = resolve_org(rec, acct, trusted, ei, cfg)
    if org.startswith("excluded:") and not elected_override:
        return exclude(org.split(":", 1)[1] + f" ({org_basis})")
    if org == "public_institution" and not cfg.elig["include_public_institutions"] and not elected_override:
        return exclude(f"public institution, not government ({org_basis})")
    if org == "unknown" and not elected_override:
        if org_q:
            row["review"].append({"on": "org", "question": org_q})
        elif ei["personal"]:
            return exclude("no organisation we can verify (personal email, no government body named)")
        else:
            row["review"].append({"on": "org", "question": f"Is '{rec.get('Company') or ei['domain']}' ({ei['domain']}) "
                                  "a government body? Org type is empty on the lead and its account."})
    row["basis"]["org"] = org_basis

    # 6. market
    market, bands_key, org_cc, m_basis = resolve_market(rec, ei, acct, trusted, cfg, dec.get("country"))
    row["org_country"] = org_cc  # bdr: picks the Danish email for NORDICS leads in DK/GL
    if dec.get("market"):
        market, m_basis = dec["market"], "review decision" + (f" (country {org_cc})" if org_cc else "")
        if not bands_key:
            bands_key = country_entry(org_cc, cfg)["bands"] if org_cc else "OTHER"
    if market is None:
        row["review"].append({"on": "market", "question": m_basis})
    else:
        row["basis"]["market"] = m_basis

    # 7. size
    size, s_basis = None, None
    if dec.get("size"):
        size, s_basis = dec["size"], "review decision"
    elif bands_key:
        size, s_basis = resolve_size(rec, acct, trusted, bands_key, cfg, dec.get("population"), dec.get("population_note"))
    if dec.get("persona"):
        persona, p_basis = dec["persona"], "review decision"
    if s_basis == UNKNOWN_SIZE and persona != "GEN":  # General has no size, so no point asking
        place = (acct.get("Name") if trusted else None) or rec.get("Company") or ei["domain"]
        row["size_check"] = (f"No population on record for '{place}' ({ei['domain'] or 'no email domain'}). "
                             "Estimate the population of the place it serves.")
    row["basis"]["size"], row["basis"]["persona"] = s_basis, p_basis
    row["market"], row["size"], row["persona"] = market, size, persona

    if not has_title(rec.get("Title"), cfg) and not ei["shared"] and "title" not in dec and "persona" not in dec:
        row["title_check"] = ("No job title on the record. Look the person up by name and organisation "
                              "and note their role.")

    # 8. a review question the decision answered is closed
    answered = {"account": "account" in dec, "org": "org" in dec, "market": "market" in dec or "country" in dec}
    row["review"] = [q for q in row["review"] if not answered.get(q["on"])]
    if row["review"]:
        row["status"] = "review"
        return row
    key = f"{market}-GEN" if persona == "GEN" else f"{market}-{persona}-{size}"
    if not KEY_RE.match(key):
        row["status"] = "review"
        row["review"].append({"on": "key", "question": f"Computed key '{key}' is not one of the 70. Check the inputs."})
        return row
    row["status"], row["key"] = "keyed", key
    return row


# ---------------------------------------------------------------- subcommands

def all_keys():
    for m in MARKETS:
        for p in ROLE_PERSONAS:
            for s in SIZES:
                yield f"{m}-{p}-{s}"
        yield f"{m}-GEN"


def cmd_keys(args):
    print("\n".join(all_keys()))


def cmd_classify(args):
    cfg = Config()
    opps_by_acct = {}
    for o in load_records(args.opps):
        opps_by_acct.setdefault(o.get("AccountId"), []).append(o)
    decisions = load_decisions(args.decisions)
    rows = [classify_lead(rec, opps_by_acct, decisions, cfg) for rec in load_records(args.leads)
            if not rec.get("IsConverted") and not rec.get(cfg.elig["run"]["write_field"])]  # never overwrite a key
    by = lambda s: [r for r in rows if r["status"] == s]
    counts, reasons = {}, {}
    for r in by("keyed"):
        counts[r["key"]] = counts.get(r["key"], 0) + 1
    for r in by("excluded"):
        k = re.sub(r" \(.*$", "", r["excluded_reason"])
        reasons[k] = reasons.get(k, 0) + 1
    plan = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "summary": {"leads": len(rows), "keyed": len(by("keyed")), "excluded": len(by("excluded")),
                        "review": len(by("review")), "size_checks": len([r for r in rows if r.get("size_check")]),
                        "title_checks": len([r for r in rows if r.get("title_check")]),
                        "by_key": dict(sorted(counts.items())),
                        "excluded_by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))},
            "rows": rows}
    Path(args.out).write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Id", cfg.elig["run"]["write_field"]])
            w.writerows([r["id"], r["key"]] for r in by("keyed"))
    s = plan["summary"]
    print(f"{s['leads']} leads without a key: {s['keyed']} keyed, {s['excluded']} excluded, {s['review']} for review, "
          f"{s['title_checks']} title checks, {s['size_checks']} size checks")
    for k, v in s["by_key"].items():
        print(f"  {k:16} {v}")
    if reasons:
        print("excluded: " + "; ".join(f"{k} {v}" for k, v in s["excluded_by_reason"].items()))
    for r in by("review"):
        print(f"REVIEW {r['id']} {r.get('company')!r} {r.get('title')!r}: " + " | ".join(q["question"] for q in r["review"]))
    names = {rec.get("Id"): " ".join(x for x in (rec.get("FirstName"), rec.get("LastName")) if x) or "(no name)"
             for rec in load_records(args.leads)}
    for r in rows:
        if r.get("title_check"):
            print(f"TITLE CHECK {r['id']} {names.get(r['id'])} | {r.get('company')} | {r.get('email_domain')}")
    for r in rows:
        if r.get("size_check") and r["status"] != "excluded":
            print(f"SIZE CHECK {r['id']} {r.get('company')!r}: {r['size_check']}")


def cmd_record(args):
    field = Config().elig["run"]["write_field"]
    plan = json.loads(Path(args.plan).read_text())
    planned = {r["id"]: r for r in plan["rows"] if r["status"] == "keyed"}
    attempted = set(args.attempted.split(",")) if args.attempted else set(planned)
    readback = {r["Id"]: r.get(field) for r in load_records(args.readback)}
    errors = {}
    if args.errors and Path(args.errors).exists():
        errors = {e["id"]: e.get("error") for e in json.loads(Path(args.errors).read_text())}
    today = args.date or dt.date.today().isoformat()
    state = Path(args.state)
    state.mkdir(exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    results = {"written": 0, "failed": 0, "not_applied": 0, "not_attempted": 0}
    log_lines, undo = [], []
    for lid, r in planned.items():
        if args.mode == "dry-run" or lid not in attempted:
            r["write"] = "dry run" if args.mode == "dry-run" else "not attempted"
            results["not_attempted"] += 1
            continue
        got = readback.get(lid)
        if lid in errors:
            result, reason = "failed", errors[lid]
        elif got == r["key"]:
            result, reason = "written", "read-back confirmed"
        else:
            result, reason = "not_applied", f"read-back shows {got!r}"
        results[result] += 1
        r["write"] = result
        log_lines.append({"ts": ts, "id": lid, "who": args.who, "field": field, "before": None, "after": r["key"],
                          "result": result, "reason": reason})
        if result == "written":
            undo.append([lid, ""])
    if log_lines:
        with open(state / "write-log.jsonl", "a") as fh:
            fh.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in log_lines)
    if undo:
        undo_path = state / f"undo-{today}.csv"
        new = not undo_path.exists()
        with open(undo_path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["Id", field])
            w.writerows(undo)
    (state / f"run-{today}.json").write_text(json.dumps(
        {"run_date": today, "mode": args.mode, "summary": plan["summary"], "writes": results, "rows": plan["rows"]},
        indent=1, ensure_ascii=False))
    with open(state / "run-log.jsonl", "a") as fh:
        fh.write(json.dumps({"run_date": today, "ts": ts, "who": args.who, "mode": args.mode, **{k: plan["summary"][k] for k in
                             ("leads", "keyed", "excluded", "review")}, **results}) + "\n")
    print(f"{args.mode}: " + ", ".join(f"{k} {v}" for k, v in results.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--leads", nargs="+", required=True, help="SOQL result JSON file(s) from the intake query")
    c.add_argument("--opps", nargs="*", help="SOQL result JSON of Opportunity (AccountId, IsClosed, IsWon)")
    c.add_argument("--decisions", default="state/review-decisions.jsonl")
    c.add_argument("--out", required=True)
    c.add_argument("--csv", help="also write Id,Persona_Key__c for a bulk import")
    r = sub.add_parser("record")
    r.add_argument("--plan", required=True)
    r.add_argument("--readback", nargs="*", help="SOQL result JSON: SELECT Id, Persona_Key__c ... WHERE Id IN (...)")
    r.add_argument("--errors", help="JSON list of {id, error} for writes the API refused")
    r.add_argument("--attempted", help="comma-separated ids actually sent (default: every keyed row)")
    r.add_argument("--mode", choices=["live", "dry-run"], required=True)
    r.add_argument("--who", default="claude", help="who ran it: an operator's name, or cloud")
    r.add_argument("--state", default="state")
    r.add_argument("--date")
    sub.add_parser("keys")
    args = ap.parse_args()
    {"classify": cmd_classify, "record": cmd_record, "keys": cmd_keys}[args.cmd](args)


if __name__ == "__main__":
    main()
