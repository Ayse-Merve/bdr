"""Deterministic rules: routing, language, status changes, templates.

Claude decides the CATEGORY of a reply (judgment). Everything that follows from
the category is computed here, so the same reply always leads to the same actions.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
TEMPLATES = ROOT / "templates"

SUPPORTED_LANGS = ["en-US", "en-GB", "fr", "nl", "nl-BE", "de", "da", "es", "it"]
MARKET_LANG = {"NAM": "en-US", "UKI": "en-GB", "NL": "nl", "BE": "nl-BE",
               "FR": "fr", "DACH": "de", "NORDICS": "en-GB", "ES": "es", "IT": "it"}
CAMPAIGN_ORDER = ["Sent", "Responded", "Meeting Booked"]
COUNTRY_LANG = {"netherlands": "nl", "the netherlands": "nl", "belgium": "nl-BE", "france": "fr",
                "germany": "de", "austria": "de", "switzerland": "de", "liechtenstein": "de",
                "united kingdom": "en-GB", "ireland": "en-GB", "denmark": "da", "greenland": "da",
                "united states": "en-US", "usa": "en-US", "italy": "it", "san marino": "it",
                "spain": "es", "mexico": "es", "chile": "es", "argentina": "es", "colombia": "es", "peru": "es",
                "ecuador": "es", "bolivia": "es", "uruguay": "es", "paraguay": "es", "venezuela": "es",
                "guatemala": "es", "honduras": "es", "el salvador": "es", "nicaragua": "es", "costa rica": "es",
                "panama": "es", "cuba": "es", "dominican republic": "es", "puerto rico": "es"}


def load(name):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def norm(s):
    return (s or "").strip().lower()


def resolve_country(country, email=None, reps=None):
    """Lead country if known, else guessed from the email's top-level domain."""
    reps = reps or load("reps.json")
    if norm(country):
        return norm(country)
    tld = norm(email).rsplit(".", 1)[-1] if email and "." in email else ""
    return reps["email_tld_to_country"].get(tld, "")


def rep_for(country, reps=None):
    reps = reps or load("reps.json")
    key = reps["country_to_rep"].get(norm(country), reps["default_rep"])
    return {"key": key, **reps["reps"][key]}


def booking_link(rep, campaign=None):
    c = campaign or load("campaign.json")
    return f"https://calendly.com/{rep['calendly_user']}/{c['calendly_slug']}?utm_source={c['utm_source']}"


def language_for(persona_key, country, reply_lang=None):
    """Answer in the language the person wrote in when we have a template for it;
    otherwise in the language of their campaign email."""
    if reply_lang in SUPPORTED_LANGS:
        return reply_lang
    if reply_lang in ("en", "nl"):
        base = MARKET_LANG.get(norm(persona_key).upper().split("-")[0], "en-US")
        if base.startswith(reply_lang):
            return base
        return {"en": "en-US", "nl": "nl"}[reply_lang]
    market = norm(persona_key).upper().split("-")[0]
    if market == "NORDICS" and norm(country) in ("denmark", "greenland"):
        return "da"
    if market in MARKET_LANG:
        return MARKET_LANG[market]
    return COUNTRY_LANG.get(norm(country), "en-US")  # no persona key on the record


def next_lead_status(current, want_mql, campaign=None):
    """Return the new Lead Status, or None to leave it. Never downgrades and
    never touches Unqualified / converted leads."""
    c = campaign or load("campaign.json")
    ls = c["lead_status"]
    if not want_mql or current in ls["never_touch"]:
        return None
    order = ls["order"]
    if current in order and order.index(current) >= order.index(ls["mql"]):
        return None
    return ls["mql"]


def next_campaign_status(current, target):
    """Return the new campaign member status, or None. Never downgrades
    (e.g. Meeting Booked stays Meeting Booked)."""
    if not target:
        return None
    if current in CAMPAIGN_ORDER and CAMPAIGN_ORDER.index(current) >= CAMPAIGN_ORDER.index(target):
        return None
    return target


def render(path, **values):
    text = (TEMPLATES / path).read_text(encoding="utf-8")
    return text.format(**{k: (v if v is not None else "") for k, v in values.items()})


def plan(*, category, email, persona_key=None, country=None, first_name=None, last_name=None,
         lead_status=None, member_status=None, record_type="Lead", reply_lang=None,
         subject=None, summary=None, original_text=None, lead_name=None, company=None,
         lead_url=None, referral_name=None):
    """Everything to do for one classified reply, as data."""
    campaign = load("campaign.json")
    reps = load("reps.json")
    rule = campaign["categories"][category]
    ctry = resolve_country(country, email, reps)
    rep = rep_for(ctry, reps)
    link = booking_link(rep, campaign)
    lang = language_for(persona_key, ctry, reply_lang)
    out = {"category": category, "country": ctry, "rep": rep, "booking_link": link,
           "language": lang, "salesforce": {}, "gmail": {}}

    sf = out["salesforce"]
    if record_type == "Lead":
        new = next_lead_status(lead_status, rule["mql"], campaign)
        if new:
            sf["lead_status"] = {"from": lead_status, "to": new}
    new_m = next_campaign_status(member_status, rule["campaign_status"])
    if new_m:
        sf["campaign_member_status"] = {"from": member_status, "to": new_m,
                                        "campaign_id": campaign["campaign_id"],
                                        "create_if_missing": member_status is None}
    if rule["opt_out"]:
        sf["email_opt_out"] = True
    if rule.get("log_task", True) and category not in ("auto_reply", "unclear"):
        sf["task"] = {"subject": f"Email reply ({category}): {subject or ''}".strip(),
                      "description": original_text or ""}

    g = out["gmail"]
    g["mode"] = campaign["mode"]
    g["labels_add"] = [campaign["gmail"]["auto_reply_label"]] if category == "auto_reply" else (
        [campaign["gmail"]["needs_review_label"]] if category == "unclear" else [campaign["gmail"]["done_label"]])
    template = rule["reply_template"]
    if template:
        g["reply"] = {"from": campaign["sender"]["email"], "to": email, "cc": rep["email"],
                      "subject": f"Re: {subject}" if subject and not norm(subject).startswith(("re:", "aw:", "sv:")) else subject,
                      "body": render(f"{template}/{lang}.md", first_name=first_name, last_name=last_name,
                                     rep_name=rep["name"], booking_link=link)}
    if rule["forward_to_rep"]:
        g["forward"] = {"from": campaign["sender"]["email"], "to": rep["email"], "reply_to": email,
                        "subject": f"[Persona reachout] {category}: {subject or ''}".strip(),
                        "body": render("rep_forward/en.md", rep_name=rep["name"], category=category,
                                       lead_name=lead_name or f"{first_name or ''} {last_name or ''}".strip(),
                                       lead_email=email, company=company, country=ctry,
                                       persona_key=persona_key, lead_url=lead_url, summary=(summary or "") + (f" | Referred to: {referral_name}" if referral_name else ""),
                                       booking_link=link, original_text=original_text)}
    if "TODO" in json.dumps(out):
        out["blocked"] = "A rep email is still TODO in config/reps.json. Fill it in before sending or forwarding."
    return out
