---
name: new-batch
description: Prepare a new batch of leads for a persona campaign - assign each lead its persona key (Borna's rules, in persona/) and build the Pardot import CSV with the ready-to-send subject and message per lead. Use when Ayse shares a leads file and says "new batch", "prepare this batch", "persona keys and messages for these leads", or similar.
---

# New batch → Pardot import CSV

Ayse uploads a leads file (CSV or Excel) in the chat. The output is a CSV she imports into Pardot herself; she then runs one Engagement Studio email that uses the merge fields. **This skill writes nothing to Salesforce or Pardot.**

Batch name: `<YYYY-MM-DD>-<short name Ayse gives, or the file name>`. Scratch: `/tmp/batch/<batch>/`. Output: `out/<batch>/` (not committed; it holds names and emails).

## 0. List already has persona keys?

If Ayse's file already has a persona key column (e.g. exported from Pardot), skip steps 2-3:

```
PYTHONPATH=src python3 -m bdr batch --keyed-csv <file.csv> --out out/<batch>
```

It needs Email and the key; it uses First/Last Name, Country and Lead ID (`CRM Lead FID`) if present. Before running, drop rows Pardot can't email (`Opted Out` = 1 or `Do Not Email` = 1) and report how many. Then go to step 4's spot-check and step 5.

## 1. Read the file

Find the **Lead ID** column (15 or 18 chars, starts with `00Q`). If there is none, use **Email**. Drop blanks and duplicates. Report the row count, and how many have neither.

## 2. Pull the leads from Salesforce (Salesforce Admin connector, `soqlQuery`)

In chunks of **200 IDs** (or emails), same fields as the persona routine:

```sql
SELECT Id, FirstName, LastName, Title, Email, Company, Country, CountryCode, StateCode, PostalCode, Status, IsConverted,
       Organization_type__c, Company_type__c, Inhabitants__c, EmailDomain__Personal_Email_Domain__c,
       Persona_Key__c, Matched_Account__c, Matched_Account__r.Name, Matched_Account__r.Population__c,
       Matched_Account__r.Inhabitants_in_numbers__c, Matched_Account__r.Inhabitants__c,
       Matched_Account__r.Organization_Type__c, Matched_Account__r.Company_Type__c,
       Matched_Account__r.Customer_Type_L1__c, Matched_Account__r.accountstatus__c,
       Matched_Account__r.RecordType.DeveloperName, Matched_Account__r.BillingCountryCode,
       Matched_Account__r.BillingStateCode, Matched_Account__r.BillingPostalCode
FROM Lead WHERE Id IN (<200 ids>)        -- or: WHERE Email IN (<200 emails>) AND IsConverted = false
```

Save each result as `/tmp/batch/<batch>/leads-<n>.json` (copy the tool-results file if the result was too big to show; never retype records). Then one Opportunity query per ≤200 distinct `Matched_Account__c`: `SELECT AccountId, IsClosed, IsWon FROM Opportunity WHERE AccountId IN (…)` → `opps-<n>.json`.

IDs/emails from the file that Salesforce doesn't return (converted, deleted, wrong): list them in the report; they get no email.

**Leads that already have a `Persona_Key__c`:** classify skips them. If the batch is meant to reuse existing keys, say so and stop; ask Ayse.

## 3. Classify (persona keys)

```
cd persona && python3 assign_persona_keys.py classify \
  --leads /tmp/batch/<batch>/leads-*.json --opps /tmp/batch/<batch>/opps-*.json \
  --decisions ../state/persona-decisions.jsonl --out /tmp/batch/<batch>/plan.json
```

It prints REVIEW rows, TITLE CHECKs and SIZE CHECKs. Decide them as in the persona routine (`persona/SKILL.md` step 4), appending one line per decision to `state/persona-decisions.jsonl`, and re-run until none are left:

- **REVIEW:** decide from the record (wrong lead country vs. a clear `.nl`/`.fr` domain, is a body government, account match). Unclear → `{"exclude": "unclear: <why>"}`.
- **SIZE CHECK:** estimate the population from what you know (`{"population": 38000, "population_note": "Bautzen, estimate"}`). No web search for batches over 50 leads; if you can't place it, skip it (the lead gets the Octopus email).
- **TITLE CHECK:** skip for batches (the lead keeps the fallback persona). Only for batches under 30 leads, and only if Ayse asks.

## 4. Build the files

```
PYTHONPATH=src python3 -m bdr batch --plan /tmp/batch/<batch>/plan.json \
  --leads /tmp/batch/<batch>/leads-*.json --out out/<batch>
```

- `pardot-import.csv`: Email, First Name, Last Name, Company, Country, Salesforce Lead ID, Persona Key, Language, **Nurture track subject**, **Nurture track message** (plain text), **Nurture track message (HTML)**. Names are already filled in (no `{{Recipient…}}` tags left); a broken or missing name gives a greeting without a name. NORDICS leads in Denmark or Greenland get the Danish version.
- `no-key.csv`: who gets no email, and why.
- `salesforce-persona-keys.csv`: `Id, Persona_Key__c`, if Ayse also wants the keys in Salesforce (Data Import Wizard, update by Id).
- `summary.json`.

Spot-check 3 rows from different languages before sending.

## 5. Hand over and record

- Send Ayse `pardot-import.csv` (and `no-key.csv`) with SendUserFile, plus a few lines: leads in, keyed (by language), no key (by reason), not found in Salesforce.
- Commit `state/persona-decisions.jsonl` and `out/<batch>/summary.json` is NOT committed (out/ is ignored); add a line to `state/batches.jsonl`: `{"batch", "date", "leads", "keyed", "no_key", "by_language"}`. Commit as `batch <batch>` and push.

## Messages

`messages/messages.json` is built from `messages/source/persona-key-messages.xlsx` (+ `messages/danish.json`). When Ayse shares a new version of the sheet: save it there and run `python3 tools/import_messages.py`, check it reports 70 keys, commit.
