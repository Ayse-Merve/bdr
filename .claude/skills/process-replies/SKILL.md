---
name: process-replies
description: Process new replies to Amy's persona reachout emails - classify each one, answer interested people with their rep's Calendly link, forward questions to the rep, and update Salesforce (Responded, MQL, Task). Use when asked to "process replies", "run the reply handler", or by the scheduled run.
---

# Process replies

Read `CLAUDE.md` first; its guardrails apply to every step. Gmail and Salesforce are reached through the **Zapier** tools (Gmail account ayse@govocal.com, Salesforce account connected by Ayse). Load them with ToolSearch if they are deferred, and use `inspect_zapier_actions` to get exact action names and parameters.

## 0. Start

- `run_id` = current UTC time as `YYYYMMDD-HHMM`.
- Read `config/campaign.json` (mode, labels, campaign id) and note the mode in your summary.
- Work from the repo root; run the CLI as `PYTHONPATH=src python3 -m bdr …`.

## 1. Collect new replies

Gmail search (Zapier "Find Email" / search action), newest first, max 50:

```
label:nurture-replies -label:nurture-replies-processed -label:nurture-replies-needs-review newer_than:14d
```

Auto-replies already carry the `Nurture replies/Auto-replies` label from Gmail's filter. Include them only to label them `Processed`; they need nothing else.

**Safety net (direct emails to Ayse):** also search `in:inbox newer_than:2d -from:govocal.com`. For each sender, check in Salesforce whether they are a member of the campaign (`CampaignMember` with that email in campaign id from config). Only those count as campaign replies: add the `Nurture replies` label and process them like the rest. Don't open or act on any other inbox email.

For each message, skip it if `python -m bdr seen <message_id>` says processed, or if its thread already has a message from amy@govocal.com sent after it.

## 2. Look up the person in Salesforce (read)

By sender email:
1. Lead with that Email and `IsConverted = false` (Id, FirstName, LastName, Company, Country, Status, Persona_Key__c).
2. Otherwise Contact with that Email (Id, FirstName, LastName, Account.Name, MailingCountry, Persona_Key__c).
3. Their `CampaignMember` in the campaign (Id, Status), if any.

No record, or several different people → label `Nurture replies/Needs review`, skip.

## 3. Classify

Use `docs/categories.md`. Read only the person's own text, not the quoted email. Decide the category and the language they wrote in. Write a one-line summary of what they want.

## 4. Get the plan

```
PYTHONPATH=src python3 -m bdr plan --category <cat> --email <sender> \
  --persona-key "<Persona_Key__c>" --country "<Country>" \
  --first-name "<FirstName>" --last-name "<LastName>" \
  --lead-status "<Status>" --member-status "<CampaignMember.Status or empty>" \
  --record-type Lead|Contact --reply-lang <lang> \
  --subject "<subject>" --summary "<one line>" --original-text "<their text>" \
  --company "<Company>" --lead-url "https://govocal.lightning.force.com/<Id>" \
  [--referral-name "<name (email)>"]   # referral only
```

Do exactly what the plan says; nothing more.

## 5. Salesforce writes (Zapier Salesforce actions)

For each item in `plan.salesforce`, log first, then write:

- `lead_status` → update the Lead's Status. `python -m bdr log-write <run_id> Lead <Id> Status "<from>" "<to>"`
- `campaign_member_status` → update the CampaignMember's Status. If `create_if_missing` and there's no member, create one (CampaignId, LeadId or ContactId, Status) and log it with old value `none`.
- `email_opt_out` → set `HasOptedOutOfEmail = true` on the Lead/Contact (Pardot picks this up as an opt-out).
- `task` → create a Task on the Lead/Contact: Subject from the plan, Description = their text, Status Completed, ActivityDate today.

If a write fails, stop processing that message, label it `Needs review`, and report the error.

## 6. Gmail

- `plan.gmail.reply` → **draft mode:** create a draft reply in the same thread, From amy@govocal.com, To the sender, CC the rep, body from the plan. **send mode:** send it.
- `plan.gmail.forward` → same, To the rep, Reply-To the prospect.
- If `plan.blocked` is set, skip reply/forward and list it in the summary.
- Add the labels in `plan.gmail.labels_add`.
- `python -m bdr mark <message_id> <sender> <category> <run_id>`

## 7. Finish

- Commit `state/` with message `run <run_id>` and push (if push fails, say so in the summary; Gmail's `Processed` label still prevents double handling).
- Summary for Ayse, one line per reply: category, person, company, what changed in Salesforce, and whether a draft/forward was created. End with counts per category and anything in `Needs review`.

## Dry run (no Gmail, no Salesforce)

To check classification and plans without touching anything: for each item in `fixtures/replies.json`, classify the `body`, compare with `expected`, run `plan` with the fixture's fields, and print a table (id, your category, expected, rep, language, Salesforce changes). Do not call any Zapier tool in a dry run.
