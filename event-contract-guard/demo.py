"""Simulated demo: 3 processors, with faults injected on purpose."""
import random
from guard import Guard, Adapter

random.seed(7)

ADAPTERS = [
    Adapter("proc_a", "type",
            {"auth": "payment.authorized", "capture": "payment.captured", "settle": "payment.settled"},
            {"payment_id": "payment_id", "amount_minor": "amount", "currency": "ccy",
             "timestamp": "ts", "settlement_batch": "batch"}),
    Adapter("proc_b", "event",
            {"AUTHORIZED": "payment.authorized", "CAPTURED": "payment.captured", "SETTLED": "payment.settled"},
            {"payment_id": "data.txn_id", "amount_minor": "data.amount_minor", "currency": "data.currency",
             "timestamp": "created_at", "settlement_batch": "data.batch_id"}),
    Adapter("proc_c", "kind",
            {"authorised": "payment.authorized", "captured": "payment.captured", "settled": "payment.settled"},
            {"payment_id": "ref", "amount_minor": "minor", "currency": "cur",
             "timestamp": "at", "settlement_batch": "batch"}),
]


def mk_a(i, stage, drift=False):
    p = {"id": f"a-{i}-{stage}", "type": stage, "payment_id": f"PA{i:03d}",
         "amount": 1000 + i, "ccy": "USD", "ts": f"2026-09-30T10:{i % 60:02d}:00Z"}
    if stage == "settle":
        p["batch"] = f"B{i // 5}"
    if drift and i >= 12:            # FAULT 1: silent type change (int -> str) + renamed field
        p["amount"] = f"{p['amount'] / 100:.2f}"
        p["currency"] = p.pop("ccy")
    return p


def mk_b(i, stage, drift=False):
    p = {"id": f"b-{i}-{stage}", "event": stage.upper(), "created_at": f"2026-09-30T11:{i % 60:02d}:00Z",
         "data": {"txn_id": f"PB{i:03d}", "amount_minor": 2000 + i, "currency": "EUR"}}
    if stage == "SETTLED":
        p["data"]["batch_id"] = f"X{i // 5}"
    if drift and i >= 8:             # FAULT 2: new field appears, nothing breaks (info only)
        p["data"]["risk_score"] = 0.12
    return p


def mk_c(i, stage):
    p = {"id": f"c-{i}-{stage}", "kind": stage, "ref": f"PC{i:03d}", "minor": 3000 + i,
         "cur": "GBP", "at": f"2026-09-30T12:{i % 60:02d}:00Z"}
    if stage == "settled":
        p["batch"] = f"Y{i // 5}"
    return p


g = Guard(ADAPTERS, baseline_size=5)

for i in range(20):
    for s in ("auth", "capture", "settle"):
        g.ingest("proc_a", mk_a(i, s, drift=True))
for i in range(20):
    for s in ("AUTHORIZED", "CAPTURED", "SETTLED"):
        g.ingest("proc_b", mk_b(i, s, drift=True))
for i in range(20):
    for s in ("authorised", "captured", "settled"):
        # FAULT 3: proc_c never sends 'captured' for payment 4, and 'settled' for 9 and 15
        if (i == 4 and s == "captured") or (i in (9, 15) and s == "settled"):
            continue
        g.ingest("proc_c", mk_c(i, s))

g.check_lifecycle()

print("=== EVENT CONTRACT GUARD - RUN REPORT ===")
print(f"canonical events accepted : {len(g.canonical_events)}")
print(f"issues raised             : {len(g.issues)}\n")
print("--- summary by processor / issue kind ---")
for proc, kinds in sorted(g.summary().items()):
    for kind, n in sorted(kinds.items()):
        print(f"{proc:7s} {kind:22s} x{n}")

print("\n--- first occurrence of each issue kind ---")
shown = set()
order = {"critical": 0, "warn": 1, "info": 2}
for i in sorted(g.issues, key=lambda x: order[x["severity"]]):
    k = (i["processor"], i["kind"], i["detail"].split(":")[0] if "drift" in i["kind"] else i["kind"])
    if (i["processor"], i["kind"]) in shown:
        continue
    shown.add((i["processor"], i["kind"]))
    print(f"[{i['severity'].upper():8s}] {i['processor']} {i['kind']}: {i['detail']}")
