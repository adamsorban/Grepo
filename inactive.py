#!/usr/bin/env python3
"""Grepolis inaktív játékos lista.

Letölti a világ nyilvános adatfájljait, összeveti az előző állapottal,
és kiírja docs/index.html-be azokat, akiknek semmi nem változott
(pont, városszám, támadó/védő pont) legalább MIN_INACTIVE_HOURS órája.
A legfrissebben inaktívak vannak elöl.
"""
import gzip
import html
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_plus
from zoneinfo import ZoneInfo

WORLD = os.environ.get("GREPO_WORLD", "hu117")
MIN_HOURS = int(os.environ.get("MIN_INACTIVE_HOURS", "24"))
BASE = f"https://{WORLD}.grepolis.com/data/"
ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
OUT = ROOT / "docs" / "index.html"
TZ = ZoneInfo("Europe/Budapest")


def fetch(name):
    req = urllib.request.Request(BASE + name, headers={"User-Agent": "inactive-list/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    return [l.split(",") for l in raw.decode("utf-8", errors="replace").splitlines() if l]


def to_int(x, default=0):
    try:
        return int(x)
    except (ValueError, TypeError):
        return default


def load_data():
    players = {}
    for r in fetch("players.txt.gz"):
        # id, name, alliance_id, points, rank, towns
        players[r[0]] = {
            "name": unquote_plus(r[1]),
            "aid": r[2],
            "points": to_int(r[3]),
            "towns": to_int(r[5]),
        }
    alliances = {r[0]: unquote_plus(r[1]) for r in fetch("alliances.txt.gz")}
    att = {r[1]: to_int(r[2]) for r in fetch("player_kills_att.txt.gz")}
    dfn = {r[1]: to_int(r[2]) for r in fetch("player_kills_def.txt.gz")}
    towns = {}
    for r in fetch("towns.txt.gz"):
        # id, player_id, name, island_x, island_y, slot, points
        if r[1]:
            towns.setdefault(r[1], []).append((to_int(r[3]), to_int(r[4]), to_int(r[6])))
    for pid, p in players.items():
        p["att"] = att.get(pid, 0)
        p["def"] = dfn.get(pid, 0)
        p["alliance"] = alliances.get(p["aid"], "")
        p["town_list"] = sorted(towns.get(pid, []), key=lambda t: -t[2])
    return players


def fmt_duration(hours):
    if hours < 48:
        return f"{int(hours)} óra"
    return f"{int(hours // 24)} nap"


def main():
    now = datetime.now(timezone.utc)
    players = load_data()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    first_run = not state

    new_state = {}
    for pid, p in players.items():
        sig = [p["points"], p["towns"], p["att"], p["def"]]
        old = state.get(pid)
        if old is None:
            # új játékos (vagy első futás): innentől figyeljük
            new_state[pid] = {"sig": sig, "changed": now.isoformat(),
                              "seen": now.isoformat(), "observed_change": False}
        elif old["sig"] != sig:
            new_state[pid] = {"sig": sig, "changed": now.isoformat(),
                              "seen": old["seen"], "observed_change": True}
        else:
            new_state[pid] = old
    STATE.write_text(json.dumps(new_state))

    rows = []
    for pid, s in new_state.items():
        p = players[pid]
        if p["towns"] <= 0:
            continue
        changed = datetime.fromisoformat(s["changed"])
        hours = (now - changed).total_seconds() / 3600
        if hours < MIN_HOURS:
            continue
        rows.append((hours, s["observed_change"], pid, p, changed))
    rows.sort(key=lambda r: r[0])  # legfrissebben inaktív elöl

    body = []
    for hours, observed, pid, p, changed in rows:
        prefix = "" if observed else "legalább "
        since = changed.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
        since_txt = since if observed else f"{since} óta biztosan (korábbról nincs adat)"
        coords = ", ".join(f"{x}|{y}" for x, y, _ in p["town_list"][:6])
        if len(p["town_list"]) > 6:
            coords += " …"
        body.append(
            "<tr>"
            f"<td>{html.escape(p['name'])}</td>"
            f"<td>{html.escape(p['alliance'])}</td>"
            f"<td>{p['points']:,}</td>"
            f"<td>{p['towns']}</td>"
            f"<td>{since_txt}</td>"
            f"<td>{prefix}{fmt_duration(hours)}</td>"
            f"<td>{coords}</td>"
            "</tr>"
        )

    updated = now.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    note = ("Első futás: az inaktivitás mérése most indult, a lista a következő napokban töltődik fel."
            if first_run else "")
    page = f"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{WORLD} inaktívak</title>
<style>
body{{font-family:system-ui,sans-serif;margin:1rem;background:#fafafa;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left}}
th{{background:#eee;position:sticky;top:0}}
small{{color:#666}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h2>{WORLD} – inaktív játékosok</h2>
<p><small>Frissítve: {updated} (budapesti idő) · Inaktív: {MIN_HOURS}+ órája nem változott
a pontja, városszáma, támadó/védő pontja · Elöl a frissebben inaktívak · {len(rows)} játékos</small></p>
<p><small>{note}</small></p>
<div class="wrap"><table>
<tr><th>Játékos</th><th>Szövetség</th><th>Pont</th><th>Városok</th>
<th>Inaktív mióta</th><th>Időtartam</th><th>Szigetek (x|y)</th></tr>
{''.join(body)}
</table></div>
</body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{len(rows)} inaktív játékos, {len(players)} összesen")


if __name__ == "__main__":
    main()
