#!/usr/bin/env python3
# CPU black-box acceptance contract regressions. Fixture traces are fabricated
# parser test data; they must never be mistaken for recorded GPU evidence.
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location("validator",Path(__file__).with_name("probe-verify-json.py"))
validator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

class EvidenceContract(unittest.TestCase):
    def run_trace(self,events,mode):
        with tempfile.TemporaryDirectory(prefix="probe-json-cpu-") as directory:
            path=Path(directory)/"fabricated-parser-fixture.jsonl"
            path.write_text("\n".join(json.dumps(v) for v in events)+"\n")
            return validator.validate(path,mode)

    def trace(self,dispatch=False):
        events=[
            {"event":"provider","id":"fixture-id","name_bytes":"FSR 4.1.1"},
            {"event":"context_provider","id":"fixture-id","selected_id_matches":True},
        ]
        if dispatch:
            events += [{"event":"api","api":"ffxDispatch synthetic upscale","ffx_code":0},
                       {"event":"dispatch_readback","frame":0,"changed_components":96*96*4,"finite_components":96*96*4}]
        events += [{"event":"result","context_provider_verified":True,
                    "dispatch_readback_completed":dispatch,"ml_dispatch_verified":False}]
        return events

    def test_context_is_not_dispatch(self):
        self.assertEqual(self.run_trace(self.trace(),"query-only")["dispatch_frames"],0)
        with self.assertRaises(ValueError): self.run_trace(self.trace(),"dispatch")

    def test_reject_false_ml_claim(self):
        events=self.trace(True); events[-1]["ml_dispatch_verified"]=True
        with self.assertRaises(ValueError): self.run_trace(events,"dispatch")

    def test_reject_unmatched_provider(self):
        events=self.trace(); events[1]["id"]="fallback"
        with self.assertRaises(ValueError): self.run_trace(events,"query-only")

    def test_reject_incomplete_readback(self):
        events=self.trace(True); events[3]["changed_components"]-=1
        with self.assertRaises(ValueError): self.run_trace(events,"dispatch")

    def test_accept_bounded_dispatch_without_ml_claim(self):
        self.assertEqual(self.run_trace(self.trace(True),"dispatch"),
                         {"context_provider_verified":True,"dispatch_frames":1,"ml_dispatch_verified":False})

if __name__=="__main__": unittest.main()
