# persona/

Persona-key rules from Borna Grunbaum's `govocal-pardot-nurture` repo (copied 2026-11-05 at fa53557), so the key decision lives in bdr.

- `assign_persona_keys.py`: works out each lead's key (`<MARKET>-<PERSONA>-<SIZE>` or `<MARKET>-GEN`). One bdr change: each plan row also carries `org_country`, used to pick the Danish email for NORDICS leads in Denmark/Greenland.
- `config.json`: every list and threshold (markets, size bands, title keywords, who gets no key). Change only when Ayse asks, then run `python3 -m unittest`.
- `SKILL.md`: the original daily routine (writes `Lead.Persona_Key__c` for new leads), kept for reference. Batches use `.claude/skills/new-batch/SKILL.md` instead.

The rules are summarised in `messages/source/persona-key-messages.xlsx` (tabs Market, Size, Persona).
