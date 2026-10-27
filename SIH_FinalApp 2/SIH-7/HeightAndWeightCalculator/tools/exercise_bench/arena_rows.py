"""Copy the Arena stress-test result (arena_bench.mjs --json) into static/validation_sim.json, so /validation
shows it. Every number comes from arena_bench_result.json - nothing is typed in by hand.

    python3 arena_tracks.py 25 && node arena_bench.mjs --json && python3 arena_rows.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "static", "validation_sim.json")
R = json.load(open(os.path.join(HERE, "arena_bench_result.json")))


def mean(a):
    return sum(a) / len(a) if a else 0.0


def both(f):
    return f(R_["old"]), f(R_["new"])


rows = []
R_ = R["dodge"]
n = R_["new"]["n"]
o, w = both(lambda r: round(mean([abs(x) for x in r["rt"]])))
rows.append({"game": "Raider Dodge", "measure": "Reaction time: average error", "trials": f"{n} dodges", "before": f"{o} ms", "now": f"{w} ms"})
o, w = both(lambda r: round(mean(r["peak"]), 1))
rows.append({"game": "Raider Dodge", "measure": "Sideways speed: average over/under-reading", "trials": f"{n} dodges",
             "before": f"{o:+.1f} shoulder widths/s", "now": f"{w:+.1f} shoulder widths/s"})
o, w = both(lambda r: r["wrong"])
rows.append({"game": "Raider Dodge", "measure": "'Started the wrong way' read wrongly", "trials": f"{n} dodges", "before": f"{o}", "now": f"{w}"})
R_ = R["jump"]
o, w = both(lambda r: round(mean([abs(x) for x in r["err"]]), 1))
rows.append({"game": "Log Jump", "measure": "Jump height: average error", "trials": f"{R_['new']['n']} jumps", "before": f"{o} cm", "now": f"{w} cm"})
o, w = both(lambda r: r["missed"])
rows.append({"game": "Log Jump", "measure": "Real jumps missed", "trials": f"{R_['new']['n']} jumps", "before": f"{o}", "now": f"{w}"})
o, w = both(lambda r: f"{r['falseClear']} of {r['nNo']}")
rows.append({"game": "Log Jump", "measure": "Rising on the toes counted as a jump", "trials": f"{R_['new']['nNo']} non-jumps", "before": o, "now": w})
R_ = R["bowler"]
o, w = both(lambda r: round(100 * r["right"] / r["n"], 1))
rows.append({"game": "Read the Bowler", "measure": "Player's answer read right", "trials": f"{R_['new']['n']} balls", "before": f"{o:g}%", "now": f"{w:g}%"})
R_ = R["escape"]
o, w = both(lambda r: sum(1 for x in r if x == 0))
rows.append({"game": "Bull Run", "measure": "Step count exactly right", "trials": f"{len(R_['new'])} runs", "before": f"{o} of {len(R_['old'])}", "now": f"{w} of {len(R_['new'])}"})
o, w = both(lambda r: round(mean([abs(x) for x in r]), 1))
rows.append({"game": "Bull Run", "measure": "Steps: average error", "trials": f"{len(R_['new'])} runs", "before": f"{o}", "now": f"{w}"})

d = json.load(open(OUT))
d["arena"] = {
    "note": "Simulated players (arena_tracks.py): the same 3-D body and camera errors as above, filmed from the front at 10-30 fps "
            "and played through the game's 60 Hz loop. Not real people. Missed steps and jumps are frames the camera dropped.",
    "rows": rows,
}
json.dump(d, open(OUT, "w"), indent=1)
for r in rows:
    print(r)
