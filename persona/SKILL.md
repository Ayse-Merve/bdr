---
name: persona-key-routine
description: Scan new Go Vocal Salesforce Leads and write each one's persona key (Lead.Persona_Key__c), the field that triggers the Pardot Engagement Studio nurture email. Use for "run the persona key routine", "assign persona keys", "backfill persona keys" or the scheduled weekday run. Writes only that field, only where blank, with read-back. Say "dry run" to write nothing.
---

# Persona-key routine

Run from the repo root. Keep scratch files in `/tmp/persona-key/`, and save every query result there as JSON. If a result was too big to show, copy the tool-results file; otherwise write out the result you got. Never type a record id by hand.

1. **New leads.** If this query fails because `Persona_Key__c` does not exist, run it again without `AND Persona_Key__c = null` and finish as a dry run.
   ```sql
   SELECT Id, FirstName, LastName, Title, Email, Company, Country, CountryCode, StateCode, PostalCode, Status, IsConverted,
          Organization_type__c, Company_type__c, Inhabitants__c, EmailDomain__Personal_Email_Domain__c,
          Persona_Key__c, Matched_Account__c, Matched_Account__r.Name, Matched_Account__r.Population__c,
          Matched_Account__r.Inhabitants_in_numbers__c, Matched_Account__r.Inhabitants__c,
          Matched_Account__r.Organization_Type__c, Matched_Account__r.Company_Type__c,
          Matched_Account__r.Customer_Type_L1__c, Matched_Account__r.accountstatus__c,
          Matched_Account__r.RecordType.DeveloperName, Matched_Account__r.BillingCountryCode,
          Matched_Account__r.BillingStateCode, Matched_Account__r.BillingPostalCode
   FROM Lead
   WHERE CreatedDate = LAST_N_DAYS:14 AND IsConverted = false AND Persona_Key__c = null
   ```
2. **Deals** on the matched accounts: `SELECT AccountId, IsClosed, IsWon FROM Opportunity WHERE AccountId IN (<distinct Matched_Account__c ids>)`.
3. **Classify:** `python3 assign_persona_keys.py classify --leads /tmp/persona-key/leads.json --opps /tmp/persona-key/opps.json --out /tmp/persona-key/plan.json`
4. **Review rows, title checks and size checks** (step 3 prints all three). Decide each one, append one line per decision to `state/review-decisions.jsonl` (lines for the same lead add up), then run step 3 again. Repeat until none are left: each lead is only asked once, but finding a title can turn a General lead into one that needs a size check.
   `{"id": "00Q…", "date": "YYYY-MM-DD", "by": "claude", "why": "…", "decision": {"account": "ignore", "org": "government"}}`
   - **Review rows:** decide from the record. Decision keys: `account` (trust | ignore), `org` (government | exclude:<reason>), `country` (ISO code), `market`, `size` (S | O | W), `persona` (ENG | DIR | POL | GEN), `exclude` (<reason>). If the record does not make it clear, decide `{"exclude": "unclear: <why>"}`.
   - **Title checks** (no job title on the record): search the person's name with the organisation. Start where elected people are listed, because that's where most hits come from: organisaties.overheid.nl in the Netherlands, the council's councillor pages in the UK, the conseil municipal page in France. Then try the organisation's staff pages and LinkedIn. Two searches at most; staff of small councils are often not online, and that's fine. Count it only when name and organisation both match, because a LinkedIn headline can be out of date. Write the role exactly as you found it, `{"title": "Communicatieadviseur", "title_source": "<url>"}`, and the script turns it into the persona with the same title rules. If nothing is found, write `{"title": "", "title_source": "not found"}` and the lead keeps the fallback (Director with a work address, General with a personal one). The role is never written to Salesforce.
   - **Size checks** (no population on record): work out which municipality, council or region the lead serves from the account name, company or email domain. Estimate its population from what you know, or with one quick web search if unsure, and write `{"population": 23000, "population_note": "Borsele municipality, estimate"}`. Give a number, never S, O or W: the script applies the market's bands. If you can't tell which place it is, skip it and the lead gets the Octopus email.
5. **Write**, unless this is a dry run. More than 50 keyed rows ⇒ re-run step 3 with `--csv state/bulk-<date>.csv` for a bulk import and stop. Otherwise, for each keyed row, call `updateSobjectRecord` with `sobject-name: Lead`, the row's `id` and body `{"Persona_Key__c": "<key>"}`. After two errors in a row, stop.
6. **Read back and record:** run `SELECT Id, Persona_Key__c FROM Lead WHERE Id IN (<ids sent>)`, then
   `python3 assign_persona_keys.py record --plan /tmp/persona-key/plan.json --readback /tmp/persona-key/readback.json --mode live --who <your name, or cloud>`
   (`--mode dry-run` with no read-back on a dry run; add `--attempted <ids>` and `--errors <file>` if the writes stopped early or failed).
7. **Report** in a few lines: leads scanned, keys written (by key), left out (by reason), review decisions taken.

**Backfill** of older leads: the same steps over a wider `CreatedDate` window. Skip step 4 and always take the CSV route.
