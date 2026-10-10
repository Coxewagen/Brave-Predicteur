import requests
import sqlite3
import json
import time
import os
import subprocess
import math
import numpy as np
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
CONFIG_FILE = "config.json"

default_config = {
    "h_start": 2.5,
    "sigma_start": 12.0,
    "k_shrink": 8,
    "injury_scale": 1.0,
    "convergence_threshold": 0.01,
    "max_iterations": 50,
    "safe_threshold": 0.60
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        default_config.update(cfg)
    return default_config

CFG = load_config()

DB_FILE = "nfl.db"
TOKEN_FILE = ".token"
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SEASON = 2026

# ============================================================
# EQUIPES
# ============================================================
TEAMS = {
    "Arizona Cardinals": {"abbr": "ARI", "nick": "Cardinals", "c1": "#97233F", "c2": "#000000"},
    "Atlanta Falcons": {"abbr": "ATL", "nick": "Falcons", "c1": "#A71930", "c2": "#000000"},
    "Baltimore Ravens": {"abbr": "BAL", "nick": "Ravens", "c1": "#241773", "c2": "#9E7C0C"},
    "Buffalo Bills": {"abbr": "BUF", "nick": "Bills", "c1": "#00338D", "c2": "#C60C30"},
    "Carolina Panthers": {"abbr": "CAR", "nick": "Panthers", "c1": "#0085CA", "c2": "#000000"},
    "Chicago Bears": {"abbr": "CHI", "nick": "Bears", "c1": "#0B162A", "c2": "#E64100"},
    "Cincinnati Bengals": {"abbr": "CIN", "nick": "Bengals", "c1": "#FB4F14", "c2": "#000000"},
    "Cleveland Browns": {"abbr": "CLE", "nick": "Browns", "c1": "#FF3C00", "c2": "#311D00"},
    "Dallas Cowboys": {"abbr": "DAL", "nick": "Cowboys", "c1": "#002244", "c2": "#B0B7BC"},
    "Denver Broncos": {"abbr": "DEN", "nick": "Broncos", "c1": "#002244", "c2": "#FB4F14"},
    "Detroit Lions": {"abbr": "DET", "nick": "Lions", "c1": "#0076B6", "c2": "#B0B7BC"},
    "Green Bay Packers": {"abbr": "GB", "nick": "Packers", "c1": "#203731", "c2": "#FFB612"},
    "Houston Texans": {"abbr": "HOU", "nick": "Texans", "c1": "#03202F", "c2": "#A71930"},
    "Indianapolis Colts": {"abbr": "IND", "nick": "Colts", "c1": "#002C5F", "c2": "#a5acaf"},
    "Jacksonville Jaguars": {"abbr": "JAX", "nick": "Jaguars", "c1": "#006778", "c2": "#000000"},
    "Kansas City Chiefs": {"abbr": "KC", "nick": "Chiefs", "c1": "#E31837", "c2": "#FFB612"},
    "Los Angeles Rams": {"abbr": "LAR", "nick": "Rams", "c1": "#003594", "c2": "#FFD100"},
    "Los Angeles Chargers": {"abbr": "LAC", "nick": "Chargers", "c1": "#007BC7", "c2": "#ffc20e"},
    "Las Vegas Raiders": {"abbr": "LV", "nick": "Raiders", "c1": "#000000", "c2": "#A5ACAF"},
    "Miami Dolphins": {"abbr": "MIA", "nick": "Dolphins", "c1": "#008E97", "c2": "#F58220"},
    "Minnesota Vikings": {"abbr": "MIN", "nick": "Vikings", "c1": "#4F2683", "c2": "#FFC62F"},
    "New England Patriots": {"abbr": "NE", "nick": "Patriots", "c1": "#002244", "c2": "#C60C30"},
    "New Orleans Saints": {"abbr": "NO", "nick": "Saints", "c1": "#D3BC8D", "c2": "#000000"},
    "New York Giants": {"abbr": "NYG", "nick": "Giants", "c1": "#0B2265", "c2": "#A71930"},
    "New York Jets": {"abbr": "NYJ", "nick": "Jets", "c1": "#003F2D", "c2": "#000000"},
    "Philadelphia Eagles": {"abbr": "PHI", "nick": "Eagles", "c1": "#004C54", "c2": "#A5ACAF"},
    "Pittsburgh Steelers": {"abbr": "PIT", "nick": "Steelers", "c1": "#000000", "c2": "#FFB612"},
    "Seattle Seahawks": {"abbr": "SEA", "nick": "Seahawks", "c1": "#002244", "c2": "#69be28"},
    "San Francisco 49ers": {"abbr": "SF", "nick": "49ers", "c1": "#AA0000", "c2": "#B3995D"},
    "Tampa Bay Buccaneers": {"abbr": "TB", "nick": "Buccaneers", "c1": "#A71930", "c2": "#322F2B"},
    "Tennessee Titans": {"abbr": "TEN", "nick": "Titans", "c1": "#4495D2", "c2": "#D50A0A"},
    "Washington Commanders": {"abbr": "WAS", "nick": "Commanders", "c1": "#5A1414", "c2": "#FFB612"}
}

# ============================================================
# BASE DE DONNEES
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            week INTEGER,
            date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT,
            season INTEGER,
            neutral INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS team_forces (
            team TEXT,
            week INTEGER,
            season INTEGER,
            off_pass REAL,
            off_run REAL,
            def_pass REAL,
            def_run REAL,
            PRIMARY KEY (team, week, season)
        );
        CREATE TABLE IF NOT EXISTS predictions (
            game_id TEXT PRIMARY KEY,
            week INTEGER,
            season INTEGER,
            home_team TEXT,
            away_team TEXT,
            p_home REAL,
            p_away REAL,
            exp_home INTEGER,
            exp_away INTEGER,
            computed_at TEXT,
            frozen INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    return conn

# ============================================================
# HELPERS
# ============================================================
def get_week(e):
    w = e.get("week", 1)
    if isinstance(w, dict):
        return int(w.get("number", 1))
    return int(w)

def get_score(c):
    s = c.get("score")
    if s is not None:
        return int(s)
    return None

# ============================================================
# FETCH ESPN
# ============================================================
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

def fetch_scoreboard(year, week=None):
    url = f"{ESPN_BASE}/scoreboard?limit=1000&season={year}"
    if week:
        url += f"&week={week}"
    data = requests.get(url).json()
    return data.get("events", [])

def fetch_current_week():
    sb = requests.get(f"{ESPN_BASE}/scoreboard").json()
    events = sb.get("events", [])
    if events:
        return get_week(events[0])
    return 1

# ============================================================
# STOCKAGE
# ============================================================
def store_games(conn, events, season):
    cursor = conn.cursor()
    for e in events:
        try:
            comp = e["competitions"][0]
            home = comp["competitors"][0]
            away = comp["competitors"][1]
            neutral = 1 if comp.get("type", {}).get("displayName") == "Neutral Site" else 0
            w = get_week(e)
            hs = get_score(home)
            as_ = get_score(away)

            cursor.execute(
                "INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    e["id"],
                    w,
                    e.get("date", ""),
                    home["team"]["displayName"],
                    away["team"]["displayName"],
                    hs,
                    as_,
                    e.get("status", {}).get("type", {}).get("name", ""),
                    season,
                    neutral
                )
            )
        except Exception as ex:
            print(f"  Erreur match {e.get('id','?')}: {ex}")
    conn.commit()

# ============================================================
# MODELE - FORCES
# ============================================================
def compute_team_forces(conn, season, week):
    cursor = conn.cursor()

    if week > 1:
        prev = cursor.execute(
            "SELECT team, off_pass, off_run, def_pass, def_run FROM team_forces WHERE season=? AND week=?",
            (season, week - 1)
        ).fetchall()
        if prev:
            forces = {r[0]: {"off_pass": r[1], "off_run": r[2], "def_pass": r[3], "def_run": r[4]} for r in prev}
        else:
            forces = {t: {"off_pass": 0.0, "off_run": 0.0, "def_pass": 0.0, "def_run": 0.0} for t in TEAMS}
    else:
        forces = {t: {"off_pass": 0.0, "off_run": 0.0, "def_pass": 0.0, "def_run": 0.0} for t in TEAMS}

    games = cursor.execute(
        "SELECT game_id, home_team, away_team, home_score, away_score FROM games WHERE season=? AND week<=? AND home_score IS NOT NULL",
        (season, week)
    ).fetchall()

    for iteration in range(CFG["max_iterations"]):
        converged = True
        for game in games:
            _, home, away, hs, as_ = game
            if home not in forces or away not in forces:
                continue

            expected_diff = (
                forces[home]["off_pass"] - forces[away]["def_pass"]
                + forces[home]["off_run"] - forces[away]["def_run"]
                + CFG["h_start"]
            )
            actual_diff = (hs or 0) - (as_ or 0)
            residual = actual_diff - expected_diff

            shrink = CFG["k_shrink"] / (CFG["k_shrink"] + iteration + 1)
            delta = residual * (1 - shrink) * 0.25

            forces[home]["off_pass"] += delta * 0.3
            forces[home]["off_run"] += delta * 0.3
            forces[away]["def_pass"] -= delta * 0.2
            forces[away]["def_run"] -= delta * 0.2

            if abs(delta) > CFG["convergence_threshold"]:
                converged = False

        if converged:
            break

    for unit in ["off_pass", "off_run", "def_pass", "def_run"]:
        vals = [forces[t][unit] for t in forces]
        mean = np.mean(vals) if vals else 0
        for t in forces:
            forces[t][unit] -= mean

    cursor = conn.cursor()
    for team, f in forces.items():
        cursor.execute(
            "INSERT OR REPLACE INTO team_forces VALUES (?,?,?,?,?,?,?)",
            (team, week, season, f["off_pass"], f["off_run"], f["def_pass"], f["def_run"])
        )
    conn.commit()

    return forces

# ============================================================
# MODELE - PREDICTION
# ============================================================
def predict_game(conn, home_team, away_team, week, season, neutral=False):
    cursor = conn.cursor()
    forces = cursor.execute(
        "SELECT team, off_pass, off_run, def_pass, def_run FROM team_forces WHERE season=? AND week=?",
        (season, week)
    ).fetchall()
    forces_dict = {r[0]: r[1:] for r in forces}

    if home_team not in forces_dict or away_team not in forces_dict:
        return None

    h_f = forces_dict[home_team]
    a_f = forces_dict[away_team]

    diff_pass = h_f[0] - a_f[3]
    diff_run = h_f[1] - a_f[2]
    h_val = 0 if neutral else CFG["h_start"]

    point_diff = (diff_pass + diff_run) * 1.0 + h_val

    sigma = CFG["sigma_start"]
    p_home = 0.5 * (1 + math.erf(point_diff / (sigma * math.sqrt(2))))
    p_away = 1 - p_home

    avg_total = 48.0
    exp_home = max(0, int((avg_total / 2) + point_diff / 2))
    exp_away = max(0, int((avg_total / 2) - point_diff / 2))

    return {
        "pHome": round(p_home, 4),
        "pAway": round(p_away, 4),
        "expHome": exp_home,
        "expAway": exp_away
    }

# ============================================================
# BUILD DATA.JSON
# ============================================================
def build_data(conn, current_week):
    cursor = conn.cursor()
    weeks_available = list(range(1, 19))

    weeks_data = {}
    for w in weeks_available:
        games_w = cursor.execute(
            "SELECT game_id, week, date, home_team, away_team, home_score, away_score, status, neutral FROM games WHERE season=? AND week=?",
            (SEASON, w)
        ).fetchall()

        games_list = []
        for g in games_w:
            game_id, week, date, home, away, hs, as_, status, neutral = g

            home_abbr = TEAMS.get(home, {}).get("abbr", home[:3].upper())
            away_abbr = TEAMS.get(away, {}).get("abbr", away[:3].upper())
            readable_id = f"{SEASON}_{week:02d}_{away_abbr}_{home_abbr}"

            pred = None
            pred_row = cursor.execute(
                "SELECT p_home, p_away, exp_home, exp_away FROM predictions WHERE game_id=?",
                (game_id,)
            ).fetchone()
            if pred_row:
                pred = {"pHome": pred_row[0], "pAway": pred_row[1], "expHome": pred_row[2], "expAway": pred_row[3]}

            entry = {
                "id": readable_id,
                "week": week,
                "home": home,
                "away": away,
                "homeScore": hs,
                "awayScore": as_,
                "status": "closed" if status == "FINAL" else "scheduled",
                "kickoff": date,
                "abs": {"home": {"qb": False, "off": 0, "deff": 0}, "away": {"qb": False, "off": 0, "deff": 0}}
            }
            if neutral:
                entry["neutral"] = True
            if pred:
                entry["pred"] = pred
            if week > current_week:
                entry["prov"] = True

            games_list.append(entry)

        weeks_data[str(w)] = games_list

    # Fiche par equipe
    fiche = {}
    for team in TEAMS:
        all_games = cursor.execute(
            "SELECT home_team, away_team, home_score, away_score, date FROM games WHERE season=? AND (home_team=? OR away_team=?) AND home_score IS NOT NULL ORDER BY date DESC",
            (SEASON, team, team)
        ).fetchall()

        wins = 0
        losses = 0
        pf = 0
        pa = 0
        form = []

        for ht, at, hs, as_, dt in all_games:
            if ht == team:
                my_score, opp_score, opp = hs, as_, at
            else:
                my_score, opp_score, opp = as_, hs, ht

            pf += my_score
            pa += opp_score
            if my_score > opp_score:
                wins += 1
                r = "V"
            else:
                losses += 1
                r = "D"

            if len(form) < 3:
                form.append({"r": r, "opp": opp, "s": f"{my_score}-{opp_score}"})

        n = wins + losses
        if n > 0:
            fiche[team] = {"rec": f"{wins}-{losses}", "pf": round(pf / n, 1), "pa": round(pa / n, 1), "form": form}
        else:
            fiche[team] = {"rec": "0-0", "pf": 0, "pa": 0, "form": []}

    # Bilan
    bilan_games = cursor.execute(
        "SELECT p_home, p_away, exp_home, exp_away, computed_at, frozen, home_team, away_team, week FROM predictions WHERE frozen=1 AND season=?",
        (SEASON,)
    ).fetchall()

    bilan_list = []
    correct = 0
    total = 0
    for row in bilan_games:
        p_home, p_away, exp_h, exp_a, computed_at, frozen, home, away, week = row
        game_row = cursor.execute(
            "SELECT home_score, away_score FROM games WHERE season=? AND home_team=? AND away_team=? AND week=?",
            (SEASON, home, away, week)
        ).fetchone()
        if game_row and game_row[0] is not None:
            hs, as_ = game_row
            total += 1
            fav_home = p_home >= p_away
            actual_home_win = hs > as_
            is_correct = (fav_home == actual_home_win)
            if is_correct:
                correct += 1
            bilan_list.append({
                "week": week, "home": home, "away": away,
                "pHome": p_home, "pAway": p_away,
                "expHome": exp_h, "expAway": exp_a,
                "computedAt": computed_at, "frozen": True,
                "homeScore": hs, "awayScore": as_, "correct": is_correct
            })

    bilan = {"total": total, "correct": correct, "safeTotal": 0, "safeCorrect": 0, "list": bilan_list}
    current_games = weeks_data.get(str(current_week), [])

    now = datetime.now()
    data = {
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M"),
        "updatedLabel": now.strftime("%d/%m/%Y a %H:%M"),
        "season": SEASON,
        "week": current_week,
        "weeksAvailable": weeks_available,
        "weeks": weeks_data,
        "teams": TEAMS,
        "fiche": fiche,
        "safe": CFG["safe_threshold"],
        "games": current_games,
        "bilan": bilan,
        "absences": []
    }
    return data

# ============================================================
# HTML
# ============================================================
def generate_html():
    return '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Predictor NFL 2026</title>
<meta name="theme-color" content="#0d2818">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@600;700&display=swap">
<style>
:root{--pitch:#0d2818;--pitch2:#0a2013;--surface:rgba(255,255,255,.055);--surface-solid:#15331f;--ink:#f2f2f0;--muted:#9fb0a8;--line:rgba(255,255,255,.16);--track:rgba(255,255,255,.1);--navy:#1d3a6e;--on-navy:#ffffff;--navy-soft:#b7c6e4;--field:#3ddc84;--on-field:#04200f;--field-bg:rgba(61,220,132,.16);--bad:#ff6b60;--bad-bg:rgba(255,107,96,.16);--warn:#ffb020;--warn-bg:rgba(255,176,32,.16);--gold:#ffb020;--gold-bg:rgba(255,176,32,.16);--sans:"IBM Plex Sans",Arial,Helvetica,sans-serif;--cond:"IBM Plex Sans Condensed","Arial Narrow",Arial,sans-serif}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{background:linear-gradient(160deg,var(--pitch),var(--pitch2));color:var(--ink);font-family:var(--sans);font-size:18px;line-height:1.45;margin:0}
svg.ic{width:1.15em;height:1.15em;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-0.2em}
.app{max-width:760px;margin:0 auto;min-height:100%;display:flex;flex-direction:column}
.topbar{background:transparent;color:var(--ink);display:flex;gap:12px;align-items:center;padding:calc(env(safe-area-inset-top,0px) + 14px) 16px 14px;border-bottom:1px solid var(--line)}
.topbar .ball{width:40px;height:40px;flex:none}
.topbar .txt{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.eyebrow{font-family:var(--cond);font-size:14px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.topbar h1{font-family:var(--cond);font-size:24px;margin:0;font-weight:700;color:var(--gold)}
.refresh{background:rgba(255,255,255,0.1);border:1px solid var(--line);color:var(--ink);width:38px;height:38px;border-radius:50%;display:grid;place-items:center;flex:none;cursor:pointer}
.refresh:active{background:rgba(255,255,255,0.28)}
main{flex:1;padding:16px;padding-bottom:28px;display:flex;flex-direction:column;gap:16px}
.view{display:flex;flex-direction:column;gap:14px}
h2{font-family:var(--cond);font-size:22px;margin:0;font-weight:700;display:flex;align-items:center;gap:9px}
h2 .sq{width:32px;height:32px;border-radius:9px;background:var(--navy);color:var(--on-navy);display:grid;place-items:center;flex:none}
.week-pager{margin-left:auto;display:flex;gap:6px;flex:none}
.pager-btn{width:30px;height:30px;border-radius:50%;background:var(--track);border:none;color:var(--ink);font-size:18px;line-height:1;display:grid;place-items:center;font-family:var(--sans);cursor:pointer}
.pager-btn:disabled{opacity:.35}
.meta{color:var(--muted);font-size:15px;margin:0}
.legend{display:flex;gap:6px 14px;flex-wrap:wrap;font-size:14px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.games{display:flex;flex-direction:column;gap:10px}
.game{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:9px}
.game.net{border-color:var(--field);box-shadow:inset 5px 0 0 var(--field)}
.ghead{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
.when{font-weight:600;color:var(--muted);font-size:15px;display:inline-flex;align-items:center;gap:6px}
.tag{font-family:var(--cond);font-size:14px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:3px 10px;border-radius:999px;display:inline-flex;align-items:center;gap:5px;background:var(--track);color:var(--muted)}
.tag.net{background:var(--field);color:var(--on-field)}
.tag.ok{background:var(--field-bg);color:var(--field)}
.tag.ko{background:var(--bad-bg);color:var(--bad)}
.team{display:flex;align-items:center;gap:10px}
.shield{width:36px;height:36px;flex:none}
.tname{font-size:17px;font-weight:500;min-width:0;flex:1;display:flex;align-items:center;gap:6px 7px;flex-wrap:wrap}
.tname.fav{font-weight:700}
.tname .short{display:none}
.role{color:var(--muted);display:inline-flex}
.chip{font-size:13px;font-weight:700;padding:1px 7px;border-radius:999px;display:inline-flex;align-items:center;gap:4px;background:var(--warn-bg);color:var(--warn)}
.chip.qb{background:var(--bad-bg);color:var(--bad)}
.pct{font-family:var(--cond);font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.pct.fav{color:var(--field)}
.gfoot{font-size:15px;color:var(--muted);display:flex;gap:4px 14px;flex-wrap:wrap}
.gfoot b{color:var(--ink);font-variant-numeric:tabular-nums}
.game.clickable{cursor:pointer}
.gtags{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.validated{display:none;font-family:var(--cond);font-size:14px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:3px 10px;border-radius:999px;align-items:center;gap:5px;background:var(--gold);color:#241a02}
.betted .validated{display:inline-flex}
.game.betted{border-color:var(--gold);box-shadow:inset 5px 0 0 var(--gold)}
.bet{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:600;color:var(--ink);cursor:pointer;padding:6px 0;align-self:flex-start;min-height:44px}
.bet input{position:absolute;opacity:0;width:1px;height:1px}
.bet .box{width:28px;height:28px;border-radius:8px;border:2px solid var(--muted);display:grid;place-items:center;flex:none;color:transparent}
.bet .box svg{width:18px;height:18px;stroke-width:3}
.bet input:checked + .box{background:var(--gold);border-color:var(--gold);color:#241a02}
.pright{display:flex;align-items:center;gap:10px;flex:none}
.pbadge{font-family:Consolas,"Courier New",monospace;font-weight:800;font-size:22px;color:#fff;border-radius:8px;padding:6px 11px;min-width:76px;text-align:center;font-variant-numeric:tabular-nums;white-space:nowrap;text-shadow:0 1px 1px rgba(0,0,0,.35)}
.pbadge.home{background:#1d3a6e}
.pbadge.away{background:#7a1f1f}
.pbadge.fav{box-shadow:0 0 0 3px var(--gold)}
.pbadge.big{font-size:34px;padding:10px 18px;min-width:118px}
.pbadge.big i{display:block;font-style:normal;font-family:var(--sans);font-size:12.5px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;opacity:.9;margin-bottom:2px}
.bigbadges{display:flex;justify-content:center;gap:14px;flex-wrap:wrap}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:1000;align-items:flex-end;justify-content:center}
.modal-overlay.open{display:flex}
.modal-panel{position:relative;width:100%;max-width:760px;max-height:85vh;overflow-y:auto;background:linear-gradient(160deg,var(--surface-solid),var(--pitch2));border-radius:18px 18px 0 0;padding:18px 16px calc(env(safe-area-inset-bottom,0px) + 18px);box-shadow:0 -10px 30px rgba(0,0,0,.4);display:flex;flex-direction:column;gap:14px}
.modal-panel .handle{width:40px;height:4px;border-radius:999px;background:var(--line);margin:0 auto}
.modal-close{position:absolute;top:12px;right:12px;width:30px;height:30px;border-radius:50%;background:var(--track);border:none;color:var(--ink);font-size:16px;line-height:1;cursor:pointer}
.mwhen{display:flex;gap:10px;align-items:center;justify-content:center;flex-wrap:wrap}
.dim{color:var(--muted);font-size:15px;font-weight:500}
.verdict{margin:0;display:flex;gap:8px;align-items:flex-start;font-size:16px;font-weight:700}
table.cmp{border-collapse:collapse;width:100%;font-size:16px;font-variant-numeric:tabular-nums}
table.cmp th{font-family:var(--cond);text-align:center;font-size:14px;color:var(--muted);border-bottom:2px solid var(--navy);padding:7px 8px}
table.cmp td{border-bottom:1px solid var(--line);padding:8px;text-align:center}
table.cmp td:first-child{color:var(--muted);font-size:15px;text-align:left}
.yes{color:var(--field);font-weight:700}
.no{color:var(--bad);font-weight:700}
.absgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
ul.abs{margin:4px 0 0;padding-left:18px}
ul.abs li{margin:3px 0;font-size:15px}
@media(max-width:380px){.tname .long{display:none}.tname .short{display:inline}}
@media(max-width:460px){.pbadge{font-size:19px;min-width:64px;padding:5px 7px}.pright{gap:7px}.pbadge.big{font-size:30px;min-width:104px;padding:9px 14px}}
@media(max-width:420px){.absgrid{grid-template-columns:1fr}}
[hidden]{display:none !important}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-home" viewBox="0 0 24 24"><path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/></symbol>
<symbol id="i-plane" viewBox="0 0 24 24"><path d="M3 13l18-8-6 16-3-7z"/></symbol>
<symbol id="i-cross" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-star" viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8 6.6 19.7l1.1-6.1L3.2 9.4l6.1-.8z"/></symbol>
<symbol id="i-cal" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></symbol>
</svg>
<div class="app">
<header class="topbar">
<svg class="ball" viewBox="0 0 54 54" aria-hidden="true"><ellipse cx="27" cy="27" rx="24" ry="14.5" transform="rotate(-35 27 27)" fill="#8A4B22" stroke="#FFFFFF" stroke-width="2.5"/><g stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round" transform="rotate(-35 27 27)"><path d="M17 27h20M21 23v8M27 23v8M33 23v8"/></g></svg>
<div class="txt"><span class="eyebrow" id="eyebrow">Saison</span><h1>Predictor NFL</h1></div>
<button class="refresh" onclick="location.reload()" title="Actualiser">&#8635;</button>
</header>
<main>
<section class="view">
<h2 class="week-head"><span class="sq"><svg class="ic"><use href="#i-cal"/></svg></span><span id="weekTitle"></span><span class="week-pager"><button type="button" id="weekPrev" class="pager-btn">&#8249;</button><button type="button" id="weekNext" class="pager-btn">&#8250;</button></span></h2>
<p class="meta" id="updatedMeta"></p>
<div class="legend"><span><svg class="ic"><use href="#i-home"/></svg>a domicile</span><span><svg class="ic"><use href="#i-plane"/></svg>a l'exterieur</span><span><span class="chip qb"><svg class="ic"><use href="#i-cross"/></svg>QB</span>absent</span><span><span class="chip"><svg class="ic"><use href="#i-cross"/></svg>2</span>autres absents</span></div>
<div class="games" id="games"></div>
</section>
</main>
</div>
<div class="modal-overlay" id="gameModalOverlay"><div class="modal-panel" id="gameModalPanel"></div></div>
<script>
var D=null;
fetch('data.json?t='+Date.now()).then(function(r){return r.json()}).then(function(d){D=d;render()});

var esc=function(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]})};
var pct=function(p){return Math.round(p*100)+" %"};
var ic=function(n){return '<svg class="ic" aria-hidden="true"><use href="#i-'+n+'"/></svg>'};
var PARIS={timeZone:"Europe/Paris"};
function when(iso){var d=new Date(iso);return d.toLocaleDateString("fr-FR",Object.assign({},PARIS,{weekday:"short",day:"numeric",month:"short"}))+" \\u00b7 "+d.toLocaleTimeString("fr-FR",Object.assign({},PARIS,{hour:"2-digit",minute:"2-digit"}))}
function lum(hex){var n=parseInt(hex.slice(1),16);return(0.299*(n>>16)+0.587*(n>>8&255)+0.114*(n&255))/255}
function shield(D2,name){var t=D2.teams[name]||{abbr:"?",c1:"#445566",c2:"#FFFFFF"};var txt=lum(t.c1)>0.6?"#0D1B2A":"#FFFFFF";var fs=t.abbr.length>2?12:15;return '<svg class="shield" viewBox="0 0 48 48"><circle cx="24" cy="24" r="22" fill="'+t.c1+'"/><path d="M8.444 39.556A22 22 0 0 0 39.556 8.444Z" fill="'+t.c2+'"/><circle cx="24" cy="24" r="21" fill="none" stroke="#f2f2f0" stroke-width="1.6" opacity=".92"/><circle cx="24" cy="24" r="22" fill="none" stroke="#10151c" stroke-width="2"/><text x="24" y="29.5" text-anchor="middle" font-family="Arial Narrow,Arial,sans-serif" font-weight="800" font-size="'+fs+'" fill="'+txt+'" stroke="rgba(0,0,0,.3)" stroke-width="2.2" style="paint-order:stroke fill">'+esc(t.abbr)+"</text></svg>"}
var nick=function(D2,name){return(D2.teams[name]||{}).nick||name};
var BETS_KEY="nfl_bets_v1";
var bets={};
try{bets=JSON.parse(localStorage.getItem(BETS_KEY)||"{}")||{}}catch(e){bets={}}
var isBet=function(id){return!!bets[id]};
function setBet(id,on){if(on)bets[id]=1;else delete bets[id];try{localStorage.setItem(BETS_KEY,JSON.stringify(bets))}catch(e){}document.querySelectorAll("[data-bet]").forEach(function(i){if(i.dataset.bet===id)i.checked=!!on});document.querySelectorAll(".game,.mwhen").forEach(function(c){if(c.dataset.id===id)c.classList.toggle("betted",!!on)})}
var betRow=function(g){return'<label class="bet"><input type="checkbox" data-bet="'+esc(g.id)+'"'+(isBet(g.id)?" checked":"")+'><span class="box">'+ic("check")+'</span><span>J\\u2019ai parie</span></label>'};
var validated=function(){return'<span class="validated">'+ic("check")+"Valide</span>"};
function weekState(D2,selected){var avail=D2.weeksAvailable||[D2.week];var minWeek=Math.min.apply(null,avail);var maxWeek=Math.max.apply(null,avail);var w=selected==null?D2.week:selected;w=Math.max(minWeek,Math.min(maxWeek,w));var title=w===D2.week?"Matchs de la semaine "+w:w<D2.week?"Semaine "+w+" (terminee)":"Semaine "+w+" (a venir)";var games=D2.weeks&&D2.weeks[String(w)]||(w===D2.week?D2.games:[])||[];return{w:w,minWeek:minWeek,maxWeek:maxWeek,title:title,games:games,future:w>D2.week}}
function gameCard(D2,g,idx){var p=g.pred,done=g.status==="closed";var favHome=p?p.pHome>=p.pAway:null;var top=p?Math.max(p.pHome,p.pAway):0;var net=p&&top>=D2.safe;var tag="";if(done&&p){var ok=g.homeScore>g.awayScore===favHome;tag=g.homeScore===g.awayScore?'<span class="tag">Match nul</span>':'<span class="tag '+(ok?"ok":"ko")+'">'+ic(ok?"check":"x")+(ok?"Prevision juste":"Prevision fausse")+"</span>"}else if(done)tag='<span class="tag">Termine</span>';else if(net)tag='<span class="tag net">'+ic("star")+"Favori net</span>";var chips=function(a){return(a.qb?'<span class="chip qb">'+ic("cross")+"QB</span>":"")+(a.off+a.deff?'<span class="chip">'+ic("cross")+(a.off+a.deff)+"</span>":"")};var line=function(side){var name=g[side];var showPct=!!p;var prob=side==="home"?p&&p.pHome:p&&p.pAway;var fav=showPct&&(side==="home"?favHome===true:favHome===false);var badge=showPct?'<span class="pbadge '+side+(fav?" fav":"")+'">'+pct(prob)+"</span>":"";var right=done?badge+'<span class="pct'+(fav?" fav":"")+'">'+(side==="home"?g.homeScore:g.awayScore)+"</span>":showPct?badge:'<span class="pct">\\u2013</span>';return'<div class="team">'+shield(D2,name)+'<span class="tname'+(fav?" fav":"")+'"><span class="long">'+esc(name)+'</span><span class="short">'+esc(nick(D2,name))+'</span><span class="role">'+ic(side==="home"?"home":"plane")+"</span>"+chips(g.abs?g.abs[side]:{})+'</span><span class="pright">'+right+"</span></div>"};var foot=[];if(done)foot.push("Resultat : <b>"+g.homeScore+" \\u2013 "+g.awayScore+"</b>");if(p)foot.push("Score attendu : <b>"+p.expHome+" \\u2013 "+p.expAway+"</b>");if(!p&&!done)foot.push("Prevision indisponible");return'<div class="game'+(net&&!done?" net":"")+(isBet(g.id)?" betted":"")+' clickable" data-idx="'+idx+'" data-id="'+esc(g.id)+'"><div class="ghead"><span class="when">'+ic("clock")+when(g.kickoff)+'</span><span class="gtags">'+validated()+tag+'</span></div>'+line("home")+line("away")+(foot.length?'<div class="gfoot">'+foot.map(function(f){return"<span>"+f+"</span>"}).join("")+"</div>":"")+betRow(g)+"</div>"}
function modalHtml(D2,g){var p=g.pred,done=g.status==="closed";var fh=(D2.fiche||{})[g.home]||{},fa=(D2.fiche||{})[g.away]||{};var pred="";if(p){var favHome=p.pHome>=p.pAway,ecart=Math.abs(p.expHome-p.expAway);var verdict=done&&g.homeScore!==g.awayScore?'<p class="verdict '+(g.homeScore>g.awayScore===favHome?"yes":"no")+'">'+ic(g.homeScore>g.awayScore===favHome?"check":"x")+(g.homeScore>g.awayScore===favHome?"Prevision juste":"Prevision fausse")+" \\u2014 resultat "+g.homeScore+" \\u2013 "+g.awayScore+" (prevu "+p.expHome+" \\u2013 "+p.expAway+")</p>":"";pred='<div class="bigbadges"><span class="pbadge big home'+(favHome?" fav":"")+'"><i>Domicile</i>'+pct(p.pHome)+'</span><span class="pbadge big away'+(!favHome?" fav":"")+'"><i>Ext\\u00e9rieur</i>'+pct(p.pAway)+'</span></div><div class="gfoot"><span>Score attendu : <b>'+p.expHome+" \\u2013 "+p.expAway+"</b></span><span>Ecart : <b>"+(ecart?esc(nick(D2,favHome?g.home:g.away))+" de "+ecart+" pt"+(ecart>1?"s":""):"aucun")+"</b></span></div>"+verdict}else{pred='<p class="meta">Pas assez de matchs joues.</p>'}var formHtml=function(t){var f=(D2.fiche||{})[t];if(!f||!f.form||!f.form.length)return"\\u2013";return f.form.map(function(x){return'<span class="'+(x.r==="V"?"yes":x.r==="D"?"no":"")+'"><b>'+x.r+'</b></span> '+esc(x.s)+' <span class="dim">vs '+esc((D2.teams[x.opp]||{}).abbr||"?")+"</span>"}).join("<br>")};var stats='<table class="cmp"><thead><tr><th></th><th>'+esc(nick(D2,g.home))+'</th><th>'+esc(nick(D2,g.away))+"</th></tr></thead><tbody><tr><td>Bilan</td><td>"+esc(fh.rec||"\\u2013")+'</td><td>'+esc(fa.rec||"\\u2013")+'</td></tr><tr><td>Points marq./match</td><td>'+(fh.pf!=null?fh.pf:"\\u2013")+'</td><td>'+(fa.pf!=null?fa.pf:"\\u2013")+'</td></tr><tr><td>Points encaiss./match</td><td>'+(fh.pa!=null?fh.pa:"\\u2013")+'</td><td>'+(fa.pa!=null?fa.pa:"\\u2013")+'</td></tr><tr><td>3 derniers</td><td>'+formHtml(g.home)+'</td><td>'+formHtml(g.away)+"</td></tr></tbody></table>";var notes=[];if(g.neutral)notes.push("Match a l'exterieur : pas d'avantage du terrain.");return'<div class="handle"></div><button class="modal-close" id="modalClose" aria-label="Fermer">\\u2715</button><div class="mwhen'+(isBet(g.id)?" betted":"")+'" data-id="'+esc(g.id)+'"><span class="when">'+ic("clock")+when(g.kickoff)+"</span>"+validated()+'</div><div class="team">'+shield(D2,g.home)+'<span class="tname"><span class="long">'+esc(g.home)+'</span><span class="role">'+ic("home")+'</span></span></div><div class="team">'+shield(D2,g.away)+'<span class="tname"><span class="long">'+esc(g.away)+'</span><span class="role">'+ic("plane")+"</span></span></div>"+betRow(g)+pred+stats+(notes.length?'<p class="meta">'+notes.join(" ")+"</p>":"")}
var $=function(id){return document.getElementById(id)};
var selectedWeek=null;
var shown=[];
function closeModal(){$("gameModalOverlay").classList.remove("open")}
function openModal(g){$("gameModalPanel").innerHTML=modalHtml(D,g);$("modalClose").addEventListener("click",closeModal);$("gameModalOverlay").classList.add("open")}
function render(){$("eyebrow").textContent="Saison "+D.season+" \\u00b7 Semaine "+D.week;var ws=weekState(D,selectedWeek);selectedWeek=ws.w;shown=ws.games;$("weekTitle").textContent=ws.title;$("updatedMeta").textContent="Mis a jour le "+D.updatedLabel+(ws.future?" \\u00b7 previsions provisoires":"");$("weekPrev").disabled=selectedWeek<=ws.minWeek;$("weekNext").disabled=selectedWeek>=ws.maxWeek;$("games").innerHTML=shown.length?shown.map(function(g,i){return gameCard(D,g,i)}).join(""):'<p class="meta">Aucun match.</p>'}
$("weekPrev").addEventListener("click",function(){if(!$("weekPrev").disabled){selectedWeek--;render()}});
$("weekNext").addEventListener("click",function(){if(!$("weekNext").disabled){selectedWeek++;render()}});
$("games").addEventListener("change",function(e){var i=e.target.closest("input[data-bet]");if(i)setBet(i.dataset.bet,i.checked)});
$("games").addEventListener("click",function(e){if(e.target.closest(".bet"))return;var card=e.target.closest(".game");if(!card)return;var g=shown[+card.dataset.idx];if(g)openModal(g)});
$("gameModalPanel").addEventListener("change",function(e){var i=e.target.closest("input[data-bet]");if(i)setBet(i.dataset.bet,i.checked)});
$("gameModalOverlay").addEventListener("click",function(e){if(e.target.id==="gameModalOverlay")closeModal()});
document.addEventListener("keydown",function(e){if(e.key==="Escape")closeModal()});
</script>
</body>
</html>'''

# ============================================================
# GIT PUSH
# ============================================================
def git_push():
    token = ""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    try:
        subprocess.run(["git", "add", "."], cwd=REPO_DIR, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                       cwd=REPO_DIR, check=True, capture_output=True)
        if token:
            url = f"https://{token}@github.com/Coxewagen/nfl-predictions.git"
            subprocess.run(["git", "push", url, "main"], cwd=REPO_DIR, check=True, capture_output=True)
        else:
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO_DIR, check=True, capture_output=True)
        print("Git push reussi.")
    except subprocess.CalledProcessError as e:
        print(f"Git push : {e.stderr.decode() if e.stderr else 'pas de changements'}")

# ============================================================
# PIPELINE
# ============================================================
def run_pipeline():
    print(f"Pipeline demarre a {datetime.now().strftime('%H:%M:%S')}")

    conn = init_db()
    week = fetch_current_week()
    print(f"  Semaine {week} {SEASON}")

    all_events = fetch_scoreboard(SEASON)
    print(f"  {len(all_events)} matchs trouves")
    store_games(conn, all_events, SEASON)

    print("  Calcul des forces...")
    compute_team_forces(conn, SEASON, week)

    cursor = conn.cursor()
    all_games = cursor.execute(
        "SELECT game_id, week, home_team, away_team, home_score, away_score, status, neutral FROM games WHERE season=?",
        (SEASON,)
    ).fetchall()

    for game_id, w, home, away, hs, as_, status, neutral in all_games:
        if w > week:
            pred = predict_game(conn, home, away, w, SEASON, bool(neutral))
            if pred:
                cursor.execute(
                    "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (game_id, w, SEASON, home, away, pred["pHome"], pred["pAway"], pred["expHome"], pred["expAway"], datetime.now().isoformat(), 0)
                )
        elif status == "FINAL" and hs is not None:
            existing = cursor.execute("SELECT 1 FROM predictions WHERE game_id=?", (game_id,)).fetchone()
            if not existing:
                pred = predict_game(conn, home, away, w, SEASON, bool(neutral))
                if pred:
                    cursor.execute(
                        "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (game_id, w, SEASON, home, away, pred["pHome"], pred["pAway"], pred["expHome"], pred["expAway"], datetime.now().isoformat(), 1)
                    )
        else:
            pred = predict_game(conn, home, away, w, SEASON, bool(neutral))
            if pred:
                cursor.execute(
                    "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (game_id, w, SEASON, home, away, pred["pHome"], pred["pAway"], pred["expHome"], pred["expAway"], datetime.now().isoformat(), 0)
                )

    conn.commit()

    data = build_data(conn, week)
    data_json_str = json.dumps(data, ensure_ascii=False)
    with open("data.json", "w", encoding="utf-8") as f:
        f.write(data_json_str)

    html = generate_html()
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    conn.close()

    print(f"  {len(data['games'])} matchs semaine {week}")
    print(f"  Bilan : {data['bilan']['correct']}/{data['bilan']['total']}")

    git_push()

    print(f"Termine a {datetime.now().strftime('%H:%M:%S')}")
    print(f"  -> https://Coxewagen.github.io/nfl-predictions/")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    run_pipeline()   