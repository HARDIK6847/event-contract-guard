"""
Event Contract Guard - prototype
Onboard a new processor/ledger via a declarative mapping, validate events against a
canonical schema, and surface schema drift + missing lifecycle events early.
Pure Python (stdlib only).
"""
from collections import defaultdict
from dataclasses import dataclass

# ---------- 1. Canonical event contract ----------
COMMON = {"payment_id": str, "amount_minor": int, "currency": str, "timestamp": str}
CANONICAL = {
    "payment.authorized": dict(COMMON),
    "payment.captured": dict(COMMON),
    "payment.settled": {**COMMON, "settlement_batch": str},
}
LIFECYCLE = ["payment.authorized", "payment.captured", "payment.settled"]


# ---------- 2. Declarative adapter (this is all a new processor needs) ----------
@dataclass
class Adapter:
    name: str
    type_field: str
    type_map: dict   # processor event type -> canonical event type
    fields: dict     # canonical field -> dotted path in processor payload


def get_path(payload, path):
    cur = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def flatten(payload, prefix=""):
    """{'a': {'b': 1}} -> {'a.b': 'int'}  (path -> type name)"""
    out = {}
    for k, v in payload.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, p + "."))
        else:
            out[p] = type(v).__name__
    return out


# ---------- 3. Guard ----------
class Guard:
    def __init__(self, adapters, baseline_size=5):
        self.adapters = {a.name: a for a in adapters}
        self.baseline_size = baseline_size
        self.baseline = defaultdict(dict)      # (proc, etype) -> {path: type}
        self.seen_count = defaultdict(int)
        self.issues = []
        self.lifecycle = defaultdict(lambda: defaultdict(set))  # proc -> pid -> {etypes}
        self.canonical_events = []

    def _issue(self, kind, severity, proc, detail, event_id=None):
        self.issues.append(dict(kind=kind, severity=severity, processor=proc,
                                detail=detail, event_id=event_id))

    def ingest(self, proc, payload):
        ad = self.adapters[proc]
        raw_type = payload.get(ad.type_field)
        etype = ad.type_map.get(raw_type)
        eid = payload.get("id") or payload.get("event_id") or "?"
        if etype is None:
            self._issue("unknown_event_type", "warn", proc,
                        f"unmapped event type '{raw_type}'", eid)
            return None

        # --- drift detection against learned baseline ---
        key = (proc, etype)
        shape = flatten(payload)
        self.seen_count[key] += 1
        if self.seen_count[key] <= self.baseline_size:
            for p, t in shape.items():          # learn during onboarding sample
                self.baseline[key].setdefault(p, t)
        else:
            base = self.baseline[key]
            for p in sorted(set(shape) - set(base)):
                self._issue("drift_new_field", "info", proc,
                            f"{etype}: new field '{p}' ({shape[p]})", eid)
            for p in sorted(set(base) - set(shape)):
                self._issue("drift_missing_field", "warn", proc,
                            f"{etype}: field '{p}' no longer sent", eid)
            for p in sorted(set(base) & set(shape)):
                if base[p] != shape[p]:
                    self._issue("drift_type_change", "critical", proc,
                                f"{etype}: '{p}' changed {base[p]} -> {shape[p]}", eid)

        # --- normalize + validate against canonical contract ---
        event = {"event_type": etype, "processor": proc}
        ok = True
        for cfield, ctype in CANONICAL[etype].items():
            path = ad.fields.get(cfield)
            val = get_path(payload, path) if path else None
            if val is None:
                self._issue("validation_missing", "critical", proc,
                            f"{etype}: '{cfield}' missing (mapped from '{path}')", eid)
                ok = False
            elif not isinstance(val, ctype) or isinstance(val, bool):
                self._issue("validation_type", "critical", proc,
                            f"{etype}: '{cfield}' expected {ctype.__name__}, "
                            f"got {type(val).__name__} ({val!r})", eid)
                ok = False
            else:
                event[cfield] = val
        if ok:
            self.canonical_events.append(event)
            self.lifecycle[proc][event["payment_id"]].add(etype)
        return event if ok else None

    # --- missing-event detection: every payment must complete the lifecycle ---
    def check_lifecycle(self):
        for proc, payments in self.lifecycle.items():
            for pid, seen in payments.items():
                last = max(LIFECYCLE.index(e) for e in seen)
                gaps = [e for e in LIFECYCLE[:last] if e not in seen]
                incomplete = LIFECYCLE[last] != LIFECYCLE[-1]
                for g in gaps:
                    self._issue("missing_event", "critical", proc,
                                f"payment {pid}: '{g}' never received "
                                f"but later stage '{LIFECYCLE[last]}' exists", pid)
                if incomplete and not gaps:
                    self._issue("stuck_payment", "warn", proc,
                                f"payment {pid}: stopped at '{LIFECYCLE[last]}', "
                                f"no '{LIFECYCLE[-1]}' yet", pid)

    def summary(self):
        by = defaultdict(lambda: defaultdict(int))
        for i in self.issues:
            by[i["processor"]][i["kind"]] += 1
        return by
