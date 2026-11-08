#!/usr/bin/env python3
"""Explicit, opt-in live model evaluation using synthetic calendar records only."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts/memories"))
import calendar_dedup as dedup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--command", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    cases = json.loads((ROOT/"tests/fixtures/calendar-dedup-eval.json").read_text())
    zone = ZoneInfo("America/New_York")
    start = int(dt.datetime(2026, 11, 10, 17, tzinfo=zone).timestamp()*1000)
    pairs, eligible = [], set()
    for i, case in enumerate(cases):
        rows = [{"sourceKey": "fixture-"+str(n), "sourceLabel": "Calendar "+str(n),
                 "event": {"title": title, "location": "", "start": start,
                           "end": start+(60+n*15)*60000, "key": "event-"+str(n)}}
                for n, title in enumerate(case["titles"])]
        if dedup.candidate(*rows):
            eligible.add(str(i))
            pairs.append({"id": str(i), "events": [dedup.model_event(r, zone) for r in rows]})
    decisions = dedup.classify({"model": args.model, "command": args.command}, pairs)
    results = []
    for i, case in enumerate(cases):
        decision = decisions.get(str(i), {"choice": "blocked-by-policy", "confidence": 0})
        accepted = decision["choice"] == "same" and decision["confidence"] >= dedup.MIN_CONFIDENCE
        results.append(dict(case, eligible=str(i) in eligible, accepted=accepted, decision=decision))
    report = {"model": args.model, "threshold": dedup.MIN_CONFIDENCE, "cases": results,
              "falsePositives": sum(x["accepted"] and not x["same"] for x in results),
              "falseNegatives": sum(not x["accepted"] and x["same"] for x in results)}
    json.dump(report, sys.stdout, indent=2)
    print()
    return int(bool(report["falsePositives"] or report["falseNegatives"]))


if __name__ == "__main__": sys.exit(main())
