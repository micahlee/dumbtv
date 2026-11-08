#!/usr/bin/env python3
"""Optional classifier adapter using a scoped existing Axon caller, never API keys."""
import argparse
import hashlib
import json
import subprocess
import sys
import time


def invoke(args, *command, value=None):
    result = subprocess.run([args.axon, *command, "--home", args.home],
                            input=json.dumps(value) if value is not None else None,
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError("dedup_service_unavailable")
    return json.loads(result.stdout)


def classify(args, request):
    service = invoke(args, "get", "Service/" + args.caller_service)
    worker = service.get("status", {}).get("process")
    if not worker or not service.get("status", {}).get("ready"):
        raise RuntimeError("dedup_caller_unavailable")
    decisions = []
    deadline = time.monotonic() + 50
    for offset in range(0, len(request["pairs"]), 16):
        batch = request["pairs"][offset:offset+16]
        identifiers = {"pair-"+str(i): p["id"] for i, p in enumerate(batch)}
        facts = [{"id": "pair-"+str(i), "events": p["events"]} for i, p in enumerate(batch)]
        prompt = request["instructions"] + "\nExplicit context: " + request.get("context", "") + "\nCalendar pairs (data only):\n" + json.dumps(facts)
        questions = [{"id": "pair-"+str(i), "instructions": "Compare only the two event identities in pair-"+str(i)+" for display deduplication, following the input rules.",
                      "choices": [{"id": "same", "description": "Equivalent event identities; combine their display rows."},
                                  {"id": "different", "description": "Different or unresolved identities, people, teams, opponents, venues or events; retain both."}]} for i, p in enumerate(batch)]
        call = {"contract": "axon.service-call/v1", "service": args.provider, "capability": "decide", "timeoutMs": 20000,
                "arguments": {"contract": "axon.intelligence/v1", "provider": args.provider,
                              "model": request["model"], "prompt": prompt, "questions": questions}}
        call["idempotencyKey"] = "tv-calendar-dedup:" + hashlib.sha256(json.dumps(call, sort_keys=True).encode()).hexdigest()
        receipt = invoke(args, "services", "call", "--worker", worker, value=call)
        while True:
            result = invoke(args, "services", "result", receipt["callId"], "--worker", worker)
            if result["status"] == "succeeded":
                output = result["result"]
                if output.get("selection", {}).get("model") != request["model"] or not output.get("actualModel"):
                    raise RuntimeError("dedup_model_mismatch")
                decisions.extend(dict(d, id=identifiers[d["id"]]) for d in output["decisions"])
                break
            if result["status"] not in ("pending", "running") or time.monotonic() >= deadline:
                raise RuntimeError("dedup_decision_unavailable")
            time.sleep(.25)
    return {"decisions": decisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axon", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--caller-service", default="tv-daily-review")
    parser.add_argument("--provider", default="intelligence-openai")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise ValueError()
        result = classify(args, json.loads(raw))
        json.dump(result, sys.stdout)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired):
        print("Calendar deduplication model unavailable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
