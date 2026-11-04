# bdr

Handles replies to Go Vocal's persona reachout emails, sent from **Amy | Go Vocal (amy@govocal.com)**.

**Flow**
1. Pardot sends the persona-key emails and adds recipients to the Salesforce campaign *LEAD ENGAGEMENT | Global Persona Based Reachout* as **Sent**.
2. Replies land in ayse@govocal.com under the Gmail label **Nurture replies** (Gmail filter on `to:amy@govocal.com`).
3. This repo (run by Claude, hourly on weekdays) classifies each reply and:
   - **interested** → reply as Amy with the rep's `go_demo_vocal` booking link (`utm_source=persona-reachout`), rep in CC · Lead → **MQL** · member → **Responded**
   - **question** → short reply as Amy ("passed to {rep}", booking link, rep in CC) + forward to the rep · Lead → **MQL** · member → **Responded**
   - **referral** → only forwarded to the rep, nothing else
   - **not interested** → member → **Responded**, no reply
   - **unsubscribe** → member → **Responded** · email opt-out
   - **left organisation / auto-reply / unclear** → no status change (unclear goes to *Needs review*)
   - every handled reply is logged as a Task
4. A booking through the link fires the Salesforce flow (Meeting Source = `persona-reachout`, SQL). Meeting Booked in this campaign is set in Pardot.

**Files**
- `CLAUDE.md`: guardrails
- `.claude/skills/process-replies/SKILL.md`: the run, step by step (+ dry run)
- `config/campaign.json`: campaign, sender, labels, mode (`draft` / `send`), status rules
- `config/reps.json`: country → rep → Calendly (Spain → Roger). **Fill in rep emails.**
- `templates/`: Amy's replies (interested, question) in 7 languages, and the forward to reps
- `docs/categories.md`: how replies are classified
- `src/bdr/`: deterministic rules (routing, language, status changes, logging) · `tests/` · `fixtures/`
- `state/`: processed messages and every Salesforce write with its old value (undo with `python -m bdr undo <run_id>`)

**Test**
```
python3 -m pytest -q tests
```
Then a dry run: ask Claude to "run process-replies as a dry run".
