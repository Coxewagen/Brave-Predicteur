import json
import math
from datetime import datetime
import nflreadpy as nfl
import requests

print("⏳ Chargement des scores via nflreadpy...")

# --- 1. Scores de tous les matchs 2026 ---
scores = nfl.load_schedules(seasons=2026)
scores = scores.filter(
    (scores["game_type"] == "REG") &
    (scores["home_score"].is_not_null()) &
    (scores["away_score"].is_not_null())
)

print(f"   {len(scores)} matchs terminés")

# --- 2. Calculer les records réels ---
teams = {}
for row in scores.iter_rows(named=True):
    home = row["home_team"]
    away = row["away_team"]
    home_score = row["home_score"] or 0
    away_score = row["away_score"] or 0

    for abbr, score, opp_score in [(home, home_score, away_score), (away, away_score, home_score)]:
        if abbr not in teams:
            teams[abbr] = {"wins": 0, "losses": 0, "pf": 0, "pa": 0, "gp": 0}
        teams[abbr]["gp"] += 1
        teams[abbr]["pf"] += score
        teams[abbr]["pa"] += opp_score
        if score > opp_score:
            teams[abbr]["wins"] += 1
        else:
            teams[abbr]["losses"] += 1

# --- 3. Mapping abbr → nom complet ---
with open("data.json") as f:
    old = json.load(f)

abbr_to_name = {}
for name, info in old.get("teams", {}).items():
    abbr_to_name[info["abbr"]] = name

print(f"\n{'Abbr':<6} {'Nom':<25} {'Rec':<8} {'PF':<6} {'PA':<6} {'Diff':<6}")
print("-" * 65)
for abbr, t in sorted(teams.items()):
    name = abbr_to_name.get(abbr, abbr)
    diff = t["pf"] - t["pa"]
    print(f"{abbr:<6} {name:<25} {t['wins']}-{t['losses']:<4} {t['pf']:<6} {t['pa']:<6} {diff:+d}")

# --- 4. Rating ---
ratings = {}
for abbr, t in teams.items():
    gp = t["gp"] if t["gp"] > 0 else 1
    diff = (t["pf"] - t["pa"]) / gp
    win_rate = t["wins"] / gp
    ratings[abbr] = diff * 0.6 + (win_rate - 0.5) * 10 * 0.4

# --- 5. Prédiction ---
HOME_ADV = 2.0

def predict(home_abbr, away_abbr):
    r_home = ratings.get(home_abbr, 0)
    r_away = ratings.get(away_abbr, 0)
    diff = r_home - r_away + HOME_ADV
    p_home = 1 / (1 + math.exp(-diff / 6))
    p_away = 1 - p_home
    base = 23
    exp_home = max(0, round(base + diff * 0.8))
    exp_away = max(0, round(base - diff * 0.8))
    return {"pHome": round(p_home, 4), "pAway": round(p_away, 4), "expHome": exp_home, "expAway": exp_away}

# --- 6. Scoreboard semaine 5 ---
print("\n⏳ Scoreboard semaine 5...")
r5 = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard")
d5 = r5.json()

games = []
for event in d5.get("events", []):
    comp = event["competitions"][0]
    home = away = None
    for c in comp["competitors"]:
        if c["homeAway"] == "home":
            home = c
        else:
            away = c
    if not home or not away:
        continue

    home_abbr = home["team"]["abbreviation"]
    away_abbr = away["team"]["abbreviation"]
    home_name = home["team"]["displayName"]
    away_name = away["team"]["displayName"]
    completed = event["status"]["type"]["completed"]

    pred = predict(home_abbr, away_abbr)

    games.append({
        "id": f"2026_05_{away_abbr}_{home_abbr}",
        "week": 5,
        "home": home_name,
        "away": away_name,
        "homeScore": int(home.get("score", 0) or 0),
        "awayScore": int(away.get("score", 0) or 0),
        "status": "final" if completed else "scheduled",
        "kickoff": event["date"],
        "abs": {"home": {"qb": False, "off": 0, "deff": 0}, "away": {"qb": False, "off": 0, "deff": 0}},
        "pred": pred
    })

# --- 7. Fiche ---
fiche = {}
for abbr, t in teams.items():
    name = abbr_to_name.get(abbr, abbr)
    fiche[name] = {"rec": f"{t['wins']}-{t['losses']}", "pf": t["pf"], "pa": t["pa"], "form": []}

# --- 8. Écrire data.json ---
data = {
    "updatedAt": datetime.now().isoformat(),
    "updatedLabel": datetime.now().strftime("%d/%m/%Y a %H:%M"),
    "season": 2026,
    "week": 5,
    "weeksAvailable": list(range(1, 19)),
    "weeks": {str(w): (games if w == 5 else []) for w in range(1, 19)},
    "teams": old.get("teams", {}),
    "fiche": fiche,
    "safe": 0.6,
    "games": games,
    "bilan": {"total": 0, "correct": 0, "safeTotal": 0, "safeCorrect": 0, "list": []},
    "absences": []
}

with open("data.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n✅ data.json mis à jour ! ({len(games)} matchs)\n")
print(f"{'Match':<50} {'Proba':<12} {'Score':<8}")
print("-" * 75)
for g in games:
    p = g["pred"]
    print(f"{g['away']} vs {g['home']:<35} {p['pHome']:.0%}/{p['pAway']:.0%}  {p['expHome']}-{p['expAway']}")   
