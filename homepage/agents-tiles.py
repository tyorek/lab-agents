#!/usr/bin/env python3
"""agents-tiles.py: put the supervisor console next to the daily digest on Homepage.

Renames the "Daily digest" group to "Agents", adds an embedded "Supervisor" console tile beside the
digest (same height), removes the old Supervisor link tile from Monitoring, and sets the Agents group
to a 2-column row. Backups: *.pre-agents-tiles. Safe to re-run.
"""
import os, shutil, sys, yaml

CFG = sys.argv[1] if len(sys.argv) > 1 else "/opt/homepage/app/config"
SVC, SET = os.path.join(CFG, "services.yaml"), os.path.join(CFG, "settings.yaml")
SRC = "https://192.168.99.3:8099/"

class D(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

def name_of(i):
    return next(iter(i)) if isinstance(i, dict) and len(i) == 1 else None

def dump(p, data):
    if not os.path.exists(p + ".pre-agents-tiles"):
        shutil.copy2(p, p + ".pre-agents-tiles")
    with open(p + ".new", "w") as f:
        yaml.dump(data, f, Dumper=D, sort_keys=False, allow_unicode=True, width=200, indent=2)
    os.replace(p + ".new", p)

svc = yaml.safe_load(open(SVC))
for g in svc:
    if name_of(g) == "Monitoring":
        g["Monitoring"] = [t for t in g["Monitoring"] if name_of(t) != "Supervisor"]

grp = next((g for g in svc if name_of(g) in ("Agents", "Daily digest")), None)
if grp is None:
    sys.exit("No 'Daily digest' group found -- nothing changed.")
old = name_of(grp)
tiles = grp.pop(old)
grp["Agents"] = tiles
digest = next((t for t in tiles if name_of(t) == "Latest digest"), None)
classes = (digest or {}).get("Latest digest", {}).get("widget", {}).get("classes", "h-96")
tiles[:] = [t for t in tiles if name_of(t) != "Supervisor"]
tiles.append({"Supervisor": {
    "description": "Ask the lab agents",
    "widget": {"type": "iframe", "name": "supervisor", "src": SRC, "classes": classes},
}})
dump(SVC, svc)

st = yaml.safe_load(open(SET)) or {}
lay = st.get("layout") or {}
new = {}
for k, v in lay.items():
    if k in ("Daily digest", "Agents"):
        new["Agents"] = {"style": "row", "columns": 2}
    else:
        new[k] = v
if "Agents" not in new:
    new["Agents"] = {"style": "row", "columns": 2}
st["layout"] = new
dump(SET, st)
print(f"'{old}' is now 'Agents': Latest digest | Supervisor console (height {classes})")
