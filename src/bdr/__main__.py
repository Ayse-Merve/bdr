"""CLI used by Claude during a run.

  python -m bdr plan --category interested --email x@y.nl --persona-key NL-GEN ...
  python -m bdr seen <message_id>
  python -m bdr mark <message_id> <email> <category> <run_id>
  python -m bdr log-write <run_id> <object> <record_id> <field> <old> <new>
  python -m bdr undo <run_id>
"""
import argparse
import json
import sys

from . import core, ledger


def main(argv=None):
    p = argparse.ArgumentParser(prog="bdr")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    for a in ["category", "email"]:
        pl.add_argument(f"--{a}", required=True)
    for a in ["persona-key", "country", "first-name", "last-name", "lead-status", "member-status", "reply-lang",
              "subject", "summary", "original-text", "lead-name", "company", "lead-url", "referral-name"]:
        pl.add_argument(f"--{a}")
    pl.add_argument("--record-type", default="Lead", choices=["Lead", "Contact"])
    s = sub.add_parser("seen"); s.add_argument("message_id")
    m = sub.add_parser("mark")
    for a in ["message_id", "email", "category", "run_id"]:
        m.add_argument(a)
    w = sub.add_parser("log-write")
    for a in ["run_id", "object", "record_id", "field", "old", "new"]:
        w.add_argument(a)
    u = sub.add_parser("undo"); u.add_argument("run_id")
    a = p.parse_args(argv)

    if a.cmd == "plan":
        out = core.plan(category=a.category, email=a.email, persona_key=a.persona_key,
                        country=a.country, first_name=a.first_name, last_name=a.last_name,
                        lead_status=a.lead_status, member_status=a.member_status,
                        record_type=a.record_type, reply_lang=a.reply_lang, subject=a.subject,
                        summary=a.summary, original_text=a.original_text, lead_name=a.lead_name,
                        company=a.company, lead_url=a.lead_url,
                        referral_name=a.referral_name)
    elif a.cmd == "seen":
        out = {"processed": ledger.is_processed(a.message_id)}
    elif a.cmd == "mark":
        ledger.mark_processed(a.message_id, a.email, a.category, a.run_id); out = {"ok": True}
    elif a.cmd == "log-write":
        ledger.log_write(a.run_id, a.object, a.record_id, a.field, a.old, a.new); out = {"ok": True}
    else:
        out = ledger.undo_list(a.run_id)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
