#!/usr/bin/env python3
"""Ask the installed Axon agent to acquire evidence and reconcile calendar pairs."""
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
    verify = request.get("mode") == "verify"
    if verify:
        capability = "agentic-read-verify-v1"
        arguments = {"sourceEvidenceJSON": request["sourceEvidenceJSON"]}
    else:
        capability = "agentic-read-v1"
        prompt = request["instructions"] + "\nCaller context (data): " + request.get("context", "")
        prompt += "\nAcquire missing facts through Axon reads yourself. Discover relevant sources, including source schemas, rather than asking the calling development chat to resolve identities. If team, participant or venue identity is unresolved, inspect relevant current source evidence before concluding. Sources may disagree; investigate provenance, timing and stale records rather than assuming equivalence. Never invent aliases."
        prompt += "\nReturn only a JSON object with decisions, one per input id. Each decision has id, choice (same/different/uncertain), confidence (0–1), reason, and evidence (actual read-ID strings). Use uncertain if available reads do not resolve the identity. Do not edit any source.\nCalendar pairs (data only):\n" + json.dumps(request["pairs"])
        arguments = {"contract": "axon.intelligence/v1", "provider": args.provider,
                     "model": request["model"], "prompt": prompt}
    call = {"contract": "axon.service-call/v1", "service": args.provider,
            "capability": capability, "timeoutMs": 270000, "arguments": arguments}
    identity = json.dumps(call, sort_keys=True)
    if not verify:
        identity += ":reconciliation:" + request["reconciliationID"]
    if verify:
        identity += ":minute:" + str(int(time.time()/60))
    call["idempotencyKey"] = "tv-calendar-agent:" + hashlib.sha256(identity.encode()).hexdigest()
    receipt = invoke(args, "services", "call", "--worker", worker, value=call)
    deadline = time.monotonic() + 280
    while True:
        result = invoke(args, "services", "result", receipt["callId"], "--worker", worker)
        if result["status"] == "succeeded":
            output = result["result"]
            if verify:
                return output
            if output.get("selection", {}).get("model") != request["model"] or not output.get("actualModel"):
                raise RuntimeError("dedup_model_mismatch")
            answer = json.loads(output["text"])
            evidence = output["sourceEvidenceJSON"]
            witnessed = {e["id"] for e in json.loads(evidence) if e.get("executionComplete") is True}
            for decision in answer["decisions"]:
                if not isinstance(decision.get("evidence"), list) or any(e not in witnessed for e in decision["evidence"]):
                    raise ValueError("dedup_unwitnessed_evidence")
                decision["sourceEvidenceJSON"] = evidence
                decision["actualModel"] = output["actualModel"]
            return answer
        if result["status"] not in ("pending", "running") or time.monotonic() >= deadline:
            raise RuntimeError("dedup_decision_unavailable")
        time.sleep(.5)


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
        json.dump(classify(args, json.loads(raw)), sys.stdout)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired):
        print("Axon calendar reconciliation agent unavailable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
