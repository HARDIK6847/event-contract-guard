# Event Contract Guard

A small prototype for onboarding a new payment processor or ledger through a declarative mapping,
validating its events against a canonical contract, and catching **schema drift** and
**missing lifecycle events** before they break reconciliation.

> Status: concept prototype. Runs on simulated events only, not on real processor traffic.
> Pure Python, standard library only.

## The problem
Every processor sends events in its own shape. Two failures are quiet and expensive:
1. **Schema drift**: a provider renames a field or changes a type without notice.
2. **Missing events**: a payment has a later lifecycle stage, but an earlier one never arrived.

## How it works
| Layer | What it does |
|---|---|
| Canonical contract | One schema per event type (authorized, captured, settled) |
| Adapter (config only) | Event-type map + canonical-field to payload-path map (dotted paths for nested JSON) |
| Validation | Normalizes events, flags missing fields and wrong types |
| Drift detector | Learns a baseline of (field path, type) from the first N events, then flags new fields (info), removed fields (warn), type changes (critical) |
| Lifecycle checker | Flags gaps and stuck payments per payment id |

Onboarding a processor is only config:

```python
Adapter("proc_b", "event",
    {"AUTHORIZED": "payment.authorized", "CAPTURED": "payment.captured", "SETTLED": "payment.settled"},
    {"payment_id": "data.txn_id", "amount_minor": "data.amount_minor",
     "currency": "data.currency", "timestamp": "created_at", "settlement_batch": "data.batch_id"})
```

## Run it
```bash
python demo.py                    # simulated run with injected faults
python -m unittest discover tests # unit tests
```
See `docs/sample_run_output.txt` and `docs/Event_Contract_Guard_Prototype.pdf`.

## Limitations
- Simulated data only.
- Baseline learning assumes the first N events are healthy. Production needs a versioned, approved baseline.
- Alerts are not yet grouped by root cause.
- No SLA windows, so it cannot distinguish "late" from "lost".

## Roadmap
- FastAPI service (`POST /events`, `GET /issues`, dry-run endpoint for onboarding).
- Incident grouping with sample payloads as evidence.
- LLM-assisted adapter drafting from API docs / sample payloads, with human review.
- SLA windows per lifecycle stage and persistent storage.
