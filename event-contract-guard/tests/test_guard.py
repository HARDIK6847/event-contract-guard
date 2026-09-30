import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from guard import Guard, Adapter

AD = Adapter("p", "type",
             {"auth": "payment.authorized", "capture": "payment.captured", "settle": "payment.settled"},
             {"payment_id": "pid", "amount_minor": "amt", "currency": "cur",
              "timestamp": "ts", "settlement_batch": "batch"})


def ev(stage, pid="P1", **over):
    e = {"id": f"{pid}-{stage}", "type": stage, "pid": pid, "amt": 100, "cur": "USD", "ts": "t"}
    if stage == "settle":
        e["batch"] = "B1"
    e.update(over)
    return e


class GuardTests(unittest.TestCase):
    def kinds(self, g):
        return {i["kind"] for i in g.issues}

    def test_clean_flow_has_no_issues(self):
        g = Guard([AD])
        for s in ("auth", "capture", "settle"):
            g.ingest("p", ev(s))
        g.check_lifecycle()
        self.assertEqual(g.issues, [])

    def test_type_change_is_drift_and_validation_error(self):
        g = Guard([AD], baseline_size=2)
        for i in range(2):
            g.ingest("p", ev("auth", pid=f"P{i}"))
        g.ingest("p", ev("auth", pid="P9", amt="1.00"))
        self.assertIn("drift_type_change", self.kinds(g))
        self.assertIn("validation_type", self.kinds(g))

    def test_new_field_is_info(self):
        g = Guard([AD], baseline_size=1)
        g.ingest("p", ev("auth", pid="P0"))
        g.ingest("p", ev("auth", pid="P1", extra=1))
        issue = [i for i in g.issues if i["kind"] == "drift_new_field"][0]
        self.assertEqual(issue["severity"], "info")

    def test_missing_captured_is_detected(self):
        g = Guard([AD])
        g.ingest("p", ev("auth"))
        g.ingest("p", ev("settle"))
        g.check_lifecycle()
        self.assertIn("missing_event", self.kinds(g))

    def test_stuck_payment(self):
        g = Guard([AD])
        g.ingest("p", ev("auth"))
        g.ingest("p", ev("capture"))
        g.check_lifecycle()
        self.assertIn("stuck_payment", self.kinds(g))

    def test_unknown_event_type(self):
        g = Guard([AD])
        g.ingest("p", ev("weird"))
        self.assertIn("unknown_event_type", self.kinds(g))


if __name__ == "__main__":
    unittest.main()
