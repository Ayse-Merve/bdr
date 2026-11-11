"""Turn a classified batch into the files Ayse uploads.

Input:  persona/assign_persona_keys.py's plan JSON + the Salesforce lead records (JSON)
Output (in out/<batch>/):
  pardot-import.csv   one row per keyed lead: email, names, persona key, ready-to-send subject and body
  no-key.csv          leads that got no key, with the reason (they get no email)
  salesforce-persona-keys.csv   Id, Persona_Key__c  (optional import, so the key also lives in Salesforce)
  summary.json        counts by key, language and reason
"""
import csv
import html
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DANISH_COUNTRIES = {"DK", "GL"}
TAG = re.compile(r"\{\{\s*Recipient\.(FirstName|LastName)\s*\}\}")


def _records(paths):
    out = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        out.extend(data.get("records", []) if isinstance(data, dict) else data)
    return out


def clean_name(n):
    """A name we can put in a greeting, or '' when it isn't one."""
    n = re.sub(r"\s+", " ", (n or "").strip())
    if not n or "?" in n or "\ufffd" in n:  # broken encoding: better no name than "J?r?me"
        return ""
    if re.search(r"[@0-9,;:/\\()]", n) or len(n) > 30 or re.search(r"\b(field|name|surname|test)\d*\b", n, re.I):
        return ""  # an email, a number, a sentence or a form placeholder
    if n.isupper() and len(n) > 2 or n.islower():
        n = " ".join(w[:1].upper() + w[1:] for w in n.lower().split(" "))
        n = "-".join(w[:1].upper() + w[1:] for w in n.split("-"))
    return n


def clean_names(first, last):
    f, l = clean_name(first), clean_name(last)
    if f and l and f.lower() == l.lower():
        l = ""  # same value typed in both fields
    if not f and l and not clean_name(first) and (first or "").strip():
        l = ""  # first name was junk: don't greet by surname alone
    return f, l


def render(text, first, last):
    """Fill the Pardot merge tags with the lead's name. With no name, the greeting
    loses the name ('Hi Anna,' -> 'Hi,'), never shows an empty tag."""
    vals = {"FirstName": first, "LastName": last}
    out = TAG.sub(lambda m: vals[m.group(1)], text)
    out = re.sub(r"[ \t]+,", ",", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out


def to_html(text):
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "".join("<p>" + html.escape(p.strip()).replace("\n", "<br>") + "</p>" for p in paras)


def pick(messages, key, org_country):
    m = messages[key]
    if key.startswith("NORDICS-") and (org_country or "").upper() in DANISH_COUNTRIES and "da" in m.get("variants", {}):
        v = m["variants"]["da"]
        return "Danish", v["subject"], v["body"]
    return m.get("language") or "", m["subject"], m["body"]


COUNTRY_DK = {"denmark", "danmark", "dk", "greenland", "grønland", "kalaallit nunaat", "gl"}


def _col(row, *names):
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v.strip()
    return ""


def from_keyed_csv(csv_path, out_dir, messages_path=None):
    """A list that already has persona keys (e.g. from Pardot): only add subject + message.
    Needs Email and a persona key column; uses First/Last Name, Country, Lead ID if present."""
    import re as _re
    rows = list(csv.DictReader(Path(csv_path).open(encoding="utf-8-sig")))
    plan, leads = {"rows": []}, []
    for i, r in enumerate(rows):
        email = _col(r, "Email", "Email Address")
        key = _col(r, "Persona Key", "Persona_Key__c", "Persona key", "PersonaKey")
        lid = _col(r, "Salesforce Lead ID", "CRM Lead FID", "Lead ID", "Id") or f"row-{i + 2}"
        country = _col(r, "Country")
        domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
        dk = country.lower() in COUNTRY_DK or (not country and domain.rsplit(".", 1)[-1] in ("dk", "gl"))
        if not email:
            plan["rows"].append({"id": lid, "status": "excluded", "excluded_reason": "no email address"})
        elif not _re.match(r"^(NAM|UKI|NL|BE|FR|DACH|NORDICS|ES|IT)-((ENG|DIR|POL)-(S|O|W)|GEN)$", key):
            plan["rows"].append({"id": lid, "status": "excluded",
                                 "excluded_reason": f"no valid persona key ({key!r})" if key else "no persona key"})
        else:
            plan["rows"].append({"id": lid, "status": "keyed", "key": key, "org_country": "DK" if dk else None})
        leads.append({"Id": lid, "Email": email, "FirstName": _col(r, "First Name", "FirstName"),
                      "LastName": _col(r, "Last Name", "LastName"), "Company": _col(r, "Company"), "Country": country})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (out / "_leads.json").write_text(json.dumps(leads, ensure_ascii=False), encoding="utf-8")
    return build(out / "_plan.json", [out / "_leads.json"], out, messages_path)


def build(plan_path, lead_paths, out_dir, messages_path=None):
    messages = json.loads(Path(messages_path or ROOT / "messages/messages.json").read_text(encoding="utf-8"))["messages"]
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    leads = {r["Id"]: r for r in _records(lead_paths)}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    keyed, nokey = [], []
    for row in plan["rows"]:
        rec = leads.get(row["id"], {})
        if row["status"] != "keyed":
            reason = row.get("excluded_reason") or "; ".join(q["question"] for q in row.get("review", [])) or row["status"]
            nokey.append({"Lead ID": row["id"], "Email": rec.get("Email"), "Company": rec.get("Company"),
                          "Status": row["status"], "Reason": reason})
            continue
        first, last = clean_names(rec.get("FirstName"), rec.get("LastName"))
        lang, subject, body = pick(messages, row["key"], row.get("org_country"))
        body = render(body, first, last)
        keyed.append({"Email": rec.get("Email"), "First Name": first, "Last Name": last,
                      "Company": rec.get("Company"), "Country": rec.get("Country"),
                      "Salesforce Lead ID": row["id"], "Persona Key": row["key"], "Language": lang,
                      "Nurture track subject": render(subject, first, last),
                      "Nurture track message": body, "Nurture track message (HTML)": to_html(body)})

    def write(name, rows, cols):
        with (out / name).open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    write("pardot-import.csv", keyed, ["Email", "First Name", "Last Name", "Company", "Country", "Salesforce Lead ID",
                                      "Persona Key", "Language", "Nurture track subject", "Nurture track message",
                                      "Nurture track message (HTML)"])
    write("no-key.csv", nokey, ["Lead ID", "Email", "Company", "Status", "Reason"])
    write("salesforce-persona-keys.csv", [{"Id": r["Salesforce Lead ID"], "Persona_Key__c": r["Persona Key"]} for r in keyed],
          ["Id", "Persona_Key__c"])
    summary = {"leads": len(plan["rows"]), "keyed": len(keyed), "no_key": len(nokey),
               "by_key": dict(sorted(Counter(r["Persona Key"] for r in keyed).items())),
               "by_language": dict(Counter(r["Language"] for r in keyed).most_common()),
               "no_key_by_reason": dict(Counter(re.sub(r" \(.*$", "", r["Reason"] or "") for r in nokey).most_common()),
               "no_name": sum(1 for r in keyed if not r["First Name"])}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary
