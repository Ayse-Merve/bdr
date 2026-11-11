"""Rebuild messages/messages.json from the messaging sheet.

  python3 tools/import_messages.py [messages/source/persona-key-messages.xlsx]

Reads the 'Messages' tab (70 keys: Subject, Email body), adds the Danish variants from
messages/danish.json and the ES/IT emails (translations of NAM) from messages/extra_markets.json. Run it whenever the sheet changes, then commit.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "messages/source/persona-key-messages.xlsx"
raw = pd.read_excel(src, sheet_name="Messages", header=None, dtype=str)
hdr = next(i for i, r in raw.iterrows() if (r == "Persona key").any())
df = pd.read_excel(src, sheet_name="Messages", header=hdr, dtype=str)
df = df[df["Persona key"].fillna("").str.match(r"^(NAM|UKI|NL|BE|FR|DACH|NORDICS)-")]
danish = json.loads((ROOT / "messages/danish.json").read_text(encoding="utf-8"))["variants"]
msgs = {}
for _, r in df.iterrows():
    k = r["Persona key"].strip()
    msgs[k] = {"language": r.get("Language"), "subject": r["Subject"].strip(), "body": r["Email body"].strip(),
               "status": r.get("Status")}
    if k in danish:
        msgs[k]["variants"] = {"da": {"language": "Danish", **danish[k]}}
extra = json.loads((ROOT / "messages/extra_markets.json").read_text(encoding="utf-8"))["messages"]
msgs.update(extra)
assert len(msgs) == 90, f"expected 90 persona keys, found {len(msgs)}"
out = ROOT / "messages/messages.json"
out.write_text(json.dumps({"_source": src.name, "messages": msgs}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(msgs)} keys, {sum('variants' in m for m in msgs.values())} with a Danish variant -> {out.relative_to(ROOT)}")
