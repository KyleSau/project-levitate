"""Smallest closing design per concept under downwash caps, from stored human-scale study experiments."""
import json
import sys
import urllib.request

B = "http://127.0.0.1:8000"
study = int(sys.argv[1]) if len(sys.argv) > 1 else 5
rows = json.load(urllib.request.urlopen(f"{B}/api/experiments?kind=human_design&study_id={study}&limit=5000"))
need = "pessimistic" if study == 6 else "nominal"
ok = [r for r in rows if (r["verdict"] == "CLOSES" if need == "pessimistic" else r["verdict"] in ("CLOSES", "CLOSES_NOMINAL_ONLY"))]
out = {}
print(f"study {study}: {len(ok)}/{len(rows)} closing ({need})")
for cap in (12, 25, 50, 1e9):
    print(f"-- jet/edge velocity <= {cap if cap < 1e9 else 'any'} m/s")
    for c in ("air_cushion", "ducted_electric", "open_rotor_electric", "ducted_hybrid", "turbojet"):
        cand = [r for r in ok if r["summary"]["concept"] == c and r["summary"]["jet_m_s"] <= cap]
        if not cand:
            print(f"   {c:20s} none")
            continue
        b = min(cand, key=lambda r: (r["summary"]["footprint_m2"], r["summary"]["cost_usd"]))
        s = b["summary"]
        out.setdefault(str(cap), {})[c] = {"id": b["id"], **s}
        print(f"   {c:20s} #{b['id']:<6} foot {s['footprint_m2']:6.2f} m2  jet {s['jet_m_s']:6.1f}  gross {s['gross_kg']:6.0f} kg"
              f"  P {s['hover_kw']:6.1f} kW  end {s['endurance_min']:5.1f} min  cost ${s['cost_usd'] / 1000:.0f}k  {s['form']}")
if len(sys.argv) > 2:
    json.dump(out, open(sys.argv[2], "w"))
