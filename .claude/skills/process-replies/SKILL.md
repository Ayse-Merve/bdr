---
name: process-replies
description: Process new replies to Amy's persona reachout emails - classify each one, answer interested people with their rep's Calendly link, forward questions to the rep, and update Salesforce (Responded, MQL, Task). Use when asked to "process replies", "run the reply handler", or by the scheduled run.
---

# Process replies

Read `CLAUDE.md` first; its guardrails apply to every step. Tools (load with ToolSearch if deferred):
- **Gmail connector** (`mcp__Gmail__*`, account ayse@govocal.com): `search_threads`, `get_thread`, `get_message`, `create_draft` (with `replyToMessageId`), `reply`, `forward`, `label_thread` / `label_message`, `list_labels`, `create_label`.
- **Salesforce Admin connector** (`mcp__Salesforce_Admin__*`): `soqlQuery` to read, `updateSobjectRecord` / `createSobjectRecord` to write. Never use its delete tools.

The Gmail tools have no From field. Replies to mail sent to amy@ must go out **from amy@govocal.com**: before the first live run, check one test draft's From. If it shows ayse@, stop and report it instead of creating replies.

## 0. Start

Scheduled: once every weekday at 09:00 (Europe/Berlin). Monday's run also covers the weekend; `Processed` labels and `state/processed.jsonl` stop anything being handled twice.

- `run_id` = current UTC time as `YYYYMMDD-HHMM`.
- Read `config/campaign.json` (mode, labels, campaign id) and note the mode in your summary.
- Work from the repo root; run the CLI as `PYTHONPATH=src python3 -m bdr …`.
- **Sender check (every run, before anything is sent):** `create_draft` to ayse@govocal.com with subject `bdr sender check <run_id>`, read it with `get_draft` (METADATA_ONLY), then `delete_draft`. The connector sends from Gmail's *default* "Send mail as" address, which must be amy@govocal.com. If the sender is anything else, treat this run as `draft` mode (create drafts, label them `Needs review`) and put "Default sender is not amy@ - change it in Gmail Settings → Accounts → Send mail as" at the top of the summary.

## 1. Collect new replies

Gmail `search_threads`, newest first, max 50:

```
label:nurture-replies -label:nurture-replies-processed -label:nurture-replies-needs-review newer_than:14d
```

Auto-replies already carry the `Nurture replies/Auto-replies` label from Gmail's filter. Include them only to label them `Processed`; they need nothing else.

**Safety net (direct emails to Ayse):** also search `in:inbox newer_than:4d -from:govocal.com`. For each sender, check in Salesforce whether they are a member of the campaign (`CampaignMember` with that email in campaign id from config). Only those count as campaign replies: add the `Nurture replies` label and process them like the rest. Don't open or act on any other inbox email.

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

## 5. Salesforce writes (Salesforce Admin connector)

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

To check classification and plans without touching anything: for each item in `fixtures/replies.json`, classify the `body`, compare with `expected`, run `plan` with the fixture's fields, and print a table (id, your category, expected, rep, language, Salesforce changes). Do not call any Gmail or Salesforce tool in a dry run.
