"""Native classifier adapter: exact pins, pair attribution and receipt reuse."""
import argparse
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts/memories"))
import axon_dedup as adapter


class AxonDedupTest(unittest.TestCase):
    def test_native_request_pins_provider_model_and_keeps_facts_in_input(self):
        args = argparse.Namespace(caller_service="fixture-caller", provider="fixture-provider")
        request = {"reconciliationID": "run-one", "model": "fixture-light", "instructions": "Classify duplicates", "pairs": [
            {"id": "opaque-original-id", "events": [{"title": "Community meeting"}, {"title": "November community meeting"}]}]}
        submitted = []
        def invoke(args, *command, value=None):
            if command[0] == "get": return {"status": {"process": "fixture-process", "ready": True}}
            if command[1] == "call":
                submitted.append(value)
                return {"callId": "fixture-call"}
            return {"status": "succeeded", "result": {"actualModel": "fixture-light-snapshot", "selection": {"model": "fixture-light"},
                    "text": json.dumps({"decisions": [{"id": "opaque-original-id", "choice": "same", "confidence": .99, "evidence": ["read-1"]}]}),
                    "sourceEvidenceJSON": json.dumps([{"id": "read-1", "query": "{fixture}", "digest": "fixture-digest", "executionComplete": True}])}}
        with patch.object(adapter, "invoke", side_effect=invoke):
            first = adapter.classify(args, request)
            adapter.classify(args, request)
            adapter.classify(args, dict(request, reconciliationID="run-two"))
        self.assertEqual(first["decisions"][0]["id"], "opaque-original-id")
        call = submitted[0]
        self.assertEqual(call["arguments"]["provider"], args.provider)
        self.assertEqual(call["arguments"]["model"], request["model"])
        self.assertIn("Community meeting", call["arguments"]["prompt"])
        self.assertEqual(call["capability"], "agentic-read-v1")
        self.assertIn("Acquire missing facts through Axon reads yourself", call["arguments"]["prompt"])
        self.assertNotIn("questions", call["arguments"])
        self.assertIn("opaque-original-id", call["arguments"]["prompt"])
        self.assertEqual(submitted[0]["idempotencyKey"], submitted[1]["idempotencyKey"])
        self.assertNotEqual(submitted[0]["idempotencyKey"], submitted[2]["idempotencyKey"])


if __name__ == "__main__": unittest.main()
