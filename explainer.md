# Payout Engine — System Explainer

> Written from the perspective of a senior backend engineer and system architect.  
> This document explains not just *what* was built, but *why* every decision was made the way it was — and what breaks if you change it.

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Architecture Overview](#2-architecture-overview)
3. [The Money Problem — Why Floats Are Banned](#3-the-money-problem--why-floats-are-banned)
4. [Ledger Design — Why There Is No Balance Column](#4-ledger-design--why-there-is-no-balance-column)
5. [Concurrency Model — SELECT FOR UPDATE](#5-concurrency-model--select-for-update)
6. [Idempotency Model](#6-idempotency-model)
7. [State Machine](#7-state-machine)
8. [The Full Request Lifecycle](#8-the-full-request-lifecycle)
9. [Celery — Async Processing & Fault Recovery](#9-celery--async-processing--fault-recovery)
10. [Atomic Refunds — The Hardest Edge Case](#10-atomic-refunds--the-hardest-edge-case)
11. [Testing Strategy](#11-testing-strategy)
12. [Database Schema Design](#12-database-schema-design)
13. [API Reference](#13-api-reference)
14. [What Deliberately Does Not Exist](#14-what-deliberately-does-not-exist)
15. [Production Deployment](#15-production-deployment)
16. [Glossary](#16-glossary)

---

## 1. What This System Does

This is a **payout engine** for Indian merchants receiving international payments. The core workflow:

1. A merchant's account is credited (e.g., from an incoming wire transfer)
2. The merchant requests a withdrawal (payout) to their Indian bank account
3. The system reserves the funds, queues the bank transfer asynchronously, and resolves the payout — completing or failing it — while maintaining a perfect audit trail

**What makes this non-trivial:**

- Money cannot be approximate. Every rupee matters.
- Two concurrent payout requests must not both succeed if there are insufficient funds.
- A crashed worker must not leave funds permanently frozen.
- A client retrying a timed-out request must not create duplicate payouts.
- Every state transition must be irreversible in the right direction.

All four of these constraints are enforced at the **database level**, not the application level. The application can crash, restart, and scale horizontally — the invariants hold regardless.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    React Dashboard                       │
│        Balance · Ledger · Payout History · Form          │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTPS / polling (3s)
┌───────────────────────▼─────────────────────────────────┐
│               Django REST Framework (Gunicorn)           │
│                                                          │
│  POST /api/v1/payouts/         ← create payout           │
│  GET  /api/v1/payouts/         ← list payouts            │
│  GET  /api/v1/balance/         ← available/held/total    │
│  GET  /api/v1/ledger/          ← full audit ledger       │
│  GET  /api/v1/merchants/       ← merchant list           │
└───────────┬──────────────────────────┬───────────────────┘
            │                          │
            ▼                          ▼
┌───────────────────┐      ┌───────────────────────┐
│    PostgreSQL      │      │    Redis (broker)      │
│                   │      └────────────┬──────────┘
│  merchants        │                   │
│  bank_accounts    │      ┌────────────▼──────────┐
│  ledger_entries ◄─┼──────│   Celery Worker+Beat  │
│  payouts          │      │                        │
│  idempotency_records│    │  process_payout()      │
└───────────────────┘      │  recover_stuck_payouts │
                           │  (every 30s via Beat)  │
                           └────────────────────────┘
```

**Technology choices:**

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | Django + DRF | Mature ORM with proper transaction support |
| Database | PostgreSQL | `SELECT FOR UPDATE`, ACID transactions, `BIGINT` arithmetic |
| Task queue | Celery + Redis | Reliable async processing with retry, acks_late |
| Frontend | React + Tailwind | Polling-based, no WebSocket complexity |
| Deployment | Railway (backend) + Vercel (frontend) | Separate concerns, independent scaling |

---

## 3. The Money Problem — Why Floats Are Banned

This is the most important design decision in the entire system.

**IEEE 754 floating point arithmetic is not safe for money:**

```python
# Python float — looks fine, isn't
>>> 0.1 + 0.2
0.30000000000000004

# At scale this compounds
>>> sum(0.1 for _ in range(1000))
99.9999999999998   # not 100.0
```

**The solution: store everything as `BIGINT` paise.**

₹1 = 100 paise. ₹500 = 50,000 paise. All amounts in the database are whole integers.

```sql
-- Schema enforces this at the DB level
amount_paise BIGINT NOT NULL CHECK (amount_paise != 0)
```

```python
# In code — every amount is an int, always
amount_paise = models.BigIntegerField()

# Display conversion is the ONLY place division happens
# and it's only for humans, never for business logic
"amount_inr": f"₹{payout.amount_paise / 100:.2f}"
```

**`BIGINT` max value = 9,223,372,036,854,775,807 paise = ₹92 trillion.** More than enough.

**Rule: `_inr` fields in API responses are display-only. Never use them in calculations.**

---

## 4. Ledger Design — Why There Is No Balance Column

Most systems store a `balance` column on the merchant record and update it on every transaction. This is wrong for three reasons:

1. **Two sources of truth** — the `balance` column and the transaction history can drift apart under concurrent writes or application bugs
2. **Not auditable** — you can't reconstruct the history from a single number
3. **Race conditions** — updating a column requires locking the merchant row, creating a global bottleneck

**This system uses an immutable ledger instead.**

```
Balance = SUM(ledger_entries.amount_paise) WHERE merchant_id = X
```

Every money event creates an immutable row:

| Event | Entry Type | Sign | Amount |
|-------|-----------|------|--------|
| Payment received | `payment_received` | + | ₹10,000 |
| Payout requested | `payout_hold` | − | ₹500 |
| Payout settled | `payout_completed` | − | ₹500 |
| Payout failed | `payout_release` | + | ₹500 |

**Balance formula (computed at DB level only):**

```sql
-- Total (all entries):
SELECT SUM(amount_paise) FROM ledger_entries WHERE merchant_id = $1;

-- Held (reserved but not yet settled):
SELECT ABS(LEAST(SUM(amount_paise), 0))
FROM ledger_entries
WHERE merchant_id = $1
  AND entry_type IN ('payout_hold', 'payout_release');

-- Available = Total − Held
```

**Ledger entries are immutable.** The ORM model uses `on_delete=PROTECT` on all foreign keys. There is no `UPDATE` or `DELETE` path in the codebase. The only write operation is `INSERT`.

---

## 5. Concurrency Model — SELECT FOR UPDATE

### The Double-Spend Problem

```
Merchant balance: ₹100

Request A: payout ₹60     ←─ arrives at the same millisecond
Request B: payout ₹60     ←─ arrives at the same millisecond
```

Without locking: both requests read balance=₹100, both pass the check, both create holds. Merchant ends up with −₹20.

**With `SELECT FOR UPDATE`:**

```
Transaction A:                      Transaction B:
  SELECT FOR UPDATE                   SELECT FOR UPDATE
  (acquires row locks)                (BLOCKS — waiting for A)
  balance = ₹100 ✓
  CREATE payout A
  INSERT hold −₹60
  COMMIT → releases locks
                                      (unblocked)
                                      balance = ₹40
                                      ₹40 < ₹60 → REJECT ✓
```

**The actual code:**

```python
with transaction.atomic():
    # Step 1: lock all ledger rows for this merchant
    # CRITICAL: select_for_update() is silently dropped by Django
    # when chained with .aggregate() — so we evaluate via list() first
    list(
        LedgerEntry.objects.select_for_update()
        .filter(merchant=merchant)
        .values("id")
    )

    # Step 2: compute balance — within the same locked transaction
    qs = LedgerEntry.objects.filter(merchant=merchant)
    total_paise = qs.aggregate(t=Sum("amount_paise"))["t"] or 0
    net_hold = qs.filter(
        entry_type__in=[LedgerEntryType.PAYOUT_HOLD, LedgerEntryType.PAYOUT_RELEASE]
    ).aggregate(h=Sum("amount_paise"))["h"] or 0

    held_paise = abs(min(net_hold, 0))
    available_paise = total_paise - held_paise

    if available_paise < amount_paise:
        raise InsufficientFundsError(...)

    # Step 3: create payout + hold in the same transaction
    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(
        amount_paise=-amount_paise,
        entry_type=LedgerEntryType.PAYOUT_HOLD,
        idempotency_key=f"hold-{payout.id}",
        ...
    )
```

**Why `list()` before `.aggregate()`:**  
Django's ORM silently drops `FOR UPDATE` when chained with `.aggregate()` because aggregations use a subquery that can't hold row-level locks. Evaluating first with `list()` forces a real `SELECT FOR UPDATE` that acquires the locks, and subsequent queries in the same transaction see the locked state.

**Lock scope:** Only ledger entries for a given `merchant_id` are locked. Two concurrent payouts from *different* merchants run fully in parallel — no cross-merchant contention.

**Why not optimistic locking (version counters)?**  
Optimistic locking pushes retry logic back to the application layer. Under high concurrency, this means re-entering the race window on every retry. `SELECT FOR UPDATE` serializes at the database — the second writer blocks and then reads the correct updated state.

---

## 6. Idempotency Model

### The Problem

A client sends a payout request. The network times out before they receive a response. Did the payout get created? They don't know. If they retry, they risk creating a duplicate.

### The Solution

Every `POST /api/v1/payouts/` request requires an `Idempotency-Key` header (UUID v4, client-generated). The first request with a given key creates the payout and stores the full response. Any subsequent request with the same key returns the **identical cached response** without re-executing.

**Scope:** Keyed per `(merchant_id, idempotency_key)`. Different merchants may use the same UUID.

**Window:** 24 hours, configurable via `PAYOUT_IDEMPOTENCY_WINDOW_HOURS`.

**What's cached:** The complete JSON response body and HTTP status code.

```python
# Check before the critical section
existing = IdempotencyRecord.objects.filter(
    merchant=merchant,
    idempotency_key=idempotency_key,
    created_at__gte=window_start,
).first()

if existing:
    return existing.response_body, 200  # exact same response, HTTP 200
```

**Conflict detection:** If the same key is reused with *different parameters* (different amount or bank account), the system raises a `409 Conflict` — not a silent duplicate, an explicit error.

### Race condition on first insert

Two concurrent requests with the same key can both pass the check and race to insert the `IdempotencyRecord`. The second hits the `UNIQUE (merchant_id, idempotency_key)` constraint:

```python
except IntegrityError:
    # Race lost — read and return the winner's response
    existing = IdempotencyRecord.objects.filter(...).first()
    if existing:
        return existing.response_body, 200
    raise  # genuine integrity error — re-raise
```

The `IdempotencyRecord` is written **inside the same transaction** as the payout and hold ledger entry — so either all three exist or none do.

---

## 7. State Machine

```
          ┌─────────┐
          │ PENDING │  ← created on POST /payouts/
          └────┬────┘
               │ Celery picks up task
               ▼
        ┌─────────────┐
        │ PROCESSING  │  ← bank API call in flight
        └──────┬──────┘
        ┌──────┴──────┐
        │             │
   bank success   bank failure (all retries exhausted)
        │             │
        ▼             ▼
  ┌──────────┐  ┌────────┐
  │COMPLETED │  │ FAILED │
  └──────────┘  └────────┘
   (terminal)    (terminal)
```

All transitions are enforced in `Payout.transition_to()`:

```python
ALLOWED_TRANSITIONS = {
    PayoutStatus.PENDING:    {PayoutStatus.PROCESSING},
    PayoutStatus.PROCESSING: {PayoutStatus.COMPLETED, PayoutStatus.FAILED},
    PayoutStatus.COMPLETED:  set(),   # terminal — no exits
    PayoutStatus.FAILED:     set(),   # terminal — no exits
}

def transition_to(self, new_status: str) -> None:
    current = PayoutStatus(self.status)
    target = PayoutStatus(new_status)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"Cannot transition payout {self.id} from {current} to {target}"
        )
    self.status = target
```

**What this prevents:**

| Attempt | Result |
|---------|--------|
| `pending → completed` | `InvalidStateTransitionError` — must go through processing |
| `completed → failed` | `InvalidStateTransitionError` — completed is terminal |
| `failed → processing` | `InvalidStateTransitionError` — failed is terminal, create a new payout |
| `processing → processing` | Allowed — idempotent re-entry for recovered tasks |

**Every state transition happens inside a `SELECT FOR UPDATE` transaction.** You cannot transition state without holding the row lock. This prevents two concurrent task instances from both advancing the same payout.

---

## 8. The Full Request Lifecycle

### Happy Path

```
POST /api/v1/payouts/
  Header: Idempotency-Key: <uuid>
  Header: X-Merchant-Id: <uuid>
  Body: { "amount_paise": 50000, "bank_account_id": "<uuid>" }

  1. Validate merchant is active
  2. Validate amount > 0 and is integer
  3. Validate bank account belongs to merchant
  4. Check idempotency cache → miss (new request)
  5. BEGIN TRANSACTION
     ├─ SELECT FOR UPDATE on all merchant ledger entries
     ├─ SUM(amount_paise) → total = 1,000,000 paise
     ├─ SUM(hold entries) → held = 0
     ├─ available = 1,000,000 ≥ 50,000 ✓
     ├─ INSERT payouts (status=pending)
     ├─ INSERT ledger_entries (type=payout_hold, amount=-50,000)
     └─ INSERT idempotency_records (response_body={...})
     COMMIT
  6. process_payout.delay(payout_id)  ← enqueued AFTER commit
  7. Return HTTP 201 { id, status: "pending", amount_paise: 50000, ... }

[Celery Worker — process_payout]
  1. SELECT FOR UPDATE on payout row
  2. payout.status == 'pending' → transition_to('processing') → COMMIT
  3. Call _simulate_bank_api() — 0.1–0.5s simulated latency
  4. Success:
     BEGIN TRANSACTION
       SELECT FOR UPDATE on payout
       transition_to('completed')
       INSERT ledger_entry (type=payout_release, amount=+50,000)
       INSERT ledger_entry (type=payout_completed, amount=-50,000)
     COMMIT
```

**Why enqueue after commit?** If the Celery task was enqueued inside the transaction and the transaction rolled back, the worker would try to process a payout that doesn't exist in the database.

### Balance After Completion

```
Ledger entries for merchant:
  payment_received   +1,000,000
  payout_hold          -50,000
  payout_release       +50,000
  payout_completed     -50,000
                     ──────────
  SUM =              +950,000   → ₹9,500 available
  held =               0        → ₹0 held
```

The release + completed pair is not redundant — the release cancels the hold entry so the "held" balance correctly shows zero after completion.

---

## 9. Celery — Async Processing & Fault Recovery

### Why async?

The bank API call takes 100–500ms (simulated). In production it could take several seconds and fail intermittently. Synchronous processing would:
- Block the API thread during the entire bank call
- Time out on client-side if the bank is slow
- Have no retry mechanism

**Celery decouples the API response from the bank interaction.**

### Task configuration

```python
@shared_task(
    bind=True,
    max_retries=3,
    acks_late=True,          # don't acknowledge until task completes
    reject_on_worker_lost=True,  # re-queue if worker dies mid-task
)
def process_payout(self, payout_id: str) -> dict:
    ...
```

`acks_late=True` is critical: the message stays in Redis until the task successfully completes. If the worker crashes mid-execution, the message is re-delivered to another worker automatically.

### Retry schedule

```python
PAYOUT_RETRY_COUNTDOWN_SECONDS = [10, 30, 90]  # attempt 1, 2, 3
```

Exponential-style backoff. After 3 failures, the payout is marked `failed` and funds are released.

### Stuck recovery — `recover_stuck_payouts`

This Beat task runs every 30 seconds and handles the scenario where a worker crashes after transitioning to `processing` but before completing:

```python
@shared_task(name="apps.payouts.tasks.recover_stuck_payouts")
def recover_stuck_payouts() -> dict:
    cutoff = timezone.now() - timedelta(seconds=PAYOUT_PROCESSING_TIMEOUT_SECONDS)

    stuck = Payout.objects.filter(
        status=PayoutStatus.PROCESSING,
        processing_started_at__lt=cutoff,    # stuck for > 30s
        attempt_count__lt=F("max_attempts"), # still has retries left
    )

    for payout in stuck:
        process_payout.delay(str(payout.id))
```

When the re-enqueued task runs, it finds the payout in `processing` state and continues from the bank API call — no double-debit risk because the state machine guard in `process_payout` handles this case explicitly.

---

## 10. Atomic Refunds — The Hardest Edge Case

When a payout fails (after all retries), two things must happen **in the same database transaction**:

1. Mark the payout as `failed`
2. Release the hold — restore merchant's available balance

```python
def _mark_failed_and_release(payout, reason: str) -> None:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(id=payout.id)
        payout.transition_to(PayoutStatus.FAILED)
        payout.failed_at = timezone.now()
        payout.failure_reason = reason
        payout.save(...)

        LedgerEntry.objects.get_or_create(
            idempotency_key=f"release-{payout.id}",  # stable key
            defaults={
                "amount_paise": +payout.amount_paise,  # positive = refund
                "entry_type": LedgerEntryType.PAYOUT_RELEASE,
                ...
            },
        )
```

**Why `get_or_create` with a stable idempotency key?**

If the worker crashes after writing `status=failed` but before writing the release entry — and the task is re-delivered — a naive `create()` would insert a second release entry, crediting the merchant twice. `get_or_create` with a stable key (`release-{payout_id}`) is idempotent: the second execution finds the existing entry and does nothing.

**Invariant:** A merchant's funds are either held (while processing) or available (after success or failure). There is no state where funds are both gone from the balance and not received by the bank.

---

## 11. Testing Strategy

### What to test and why

**Unit tests — state machine**
```python
def test_invalid_transition_pending_to_completed():
    payout = Payout(status=PayoutStatus.PENDING)
    with pytest.raises(InvalidStateTransitionError):
        payout.transition_to(PayoutStatus.COMPLETED)

def test_terminal_states_have_no_exits():
    for terminal in [PayoutStatus.COMPLETED, PayoutStatus.FAILED]:
        payout = Payout(status=terminal)
        for target in PayoutStatus:
            with pytest.raises(InvalidStateTransitionError):
                payout.transition_to(target)
```

**Integration tests — the double-spend scenario**
```python
def test_concurrent_payouts_cannot_overdraw(db):
    # Merchant has ₹100
    merchant = create_merchant_with_balance(10000)

    # Fire two ₹60 payouts concurrently via threads
    results = run_concurrent(
        lambda: create_payout(merchant, amount_paise=6000, ...),
        lambda: create_payout(merchant, amount_paise=6000, ...),
    )

    # Exactly one must succeed, one must fail with InsufficientFundsError
    successes = [r for r in results if r["status"] == "pending"]
    failures  = [r for r in results if "insufficient_funds" in r.get("error", "")]

    assert len(successes) == 1
    assert len(failures)  == 1
```

**Integration tests — idempotency**
```python
def test_same_key_returns_identical_response(db):
    key = str(uuid.uuid4())
    r1 = create_payout(idempotency_key=key, amount_paise=5000)
    r2 = create_payout(idempotency_key=key, amount_paise=5000)

    assert r1 == r2                      # byte-identical response
    assert Payout.objects.count() == 1   # only one payout created

def test_same_key_different_params_returns_409(db):
    key = str(uuid.uuid4())
    create_payout(idempotency_key=key, amount_paise=5000)

    with pytest.raises(IdempotencyConflictError):
        create_payout(idempotency_key=key, amount_paise=9999)
```

**Integration tests — atomic refund**
```python
def test_failed_payout_releases_funds(db):
    merchant = create_merchant_with_balance(10000)
    payout = create_payout(merchant, amount_paise=5000)

    # Balance should be held during processing
    assert get_balance(merchant)["held_paise"] == 5000
    assert get_balance(merchant)["available_paise"] == 5000

    # Simulate failure
    _mark_failed_and_release(payout, reason="bank_timeout")

    # All funds must be restored
    assert get_balance(merchant)["held_paise"] == 0
    assert get_balance(merchant)["available_paise"] == 10000
    assert Payout.objects.get(id=payout.id).status == "failed"
```

**Integration tests — stuck recovery**
```python
def test_recover_stuck_payouts_re_enqueues(db, celery_eager):
    payout = create_payout_in_processing_state(stuck_for_seconds=60)

    result = recover_stuck_payouts()

    assert result["recovered"] == 1
    payout.refresh_from_db()
    assert payout.status != PayoutStatus.PROCESSING
```

### What NOT to mock
The lock behaviour (`SELECT FOR UPDATE`) must be tested against a real PostgreSQL instance, not SQLite. SQLite does not support row-level locking and will give false passing results for concurrency tests.

---

## 12. Database Schema Design

### `ledger_entries` — The Core Table

```sql
CREATE TABLE ledger_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id),
    amount_paise    BIGINT NOT NULL CHECK (amount_paise != 0),
    entry_type      VARCHAR(30) NOT NULL,
    payout_id       UUID REFERENCES payouts(id),
    idempotency_key VARCHAR(100) UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON ledger_entries(merchant_id, created_at DESC);
CREATE INDEX ON ledger_entries(merchant_id, entry_type);
```

The `CHECK (amount_paise != 0)` constraint prevents zero-amount entries at the database level — no application code needed.

`idempotency_key UNIQUE` on ledger entries prevents duplicate entries if the same Celery task runs twice (worker restart, re-delivery).

### Index design rationale

| Index | Query it serves |
|-------|----------------|
| `(merchant_id, created_at DESC)` | Ledger history view, paginated |
| `(merchant_id, entry_type)` | Balance calculation (hold filter) |
| `(payout_id)` | "Show all entries for this payout" |
| `(merchant_id, status)` on payouts | "Show all pending payouts for merchant" |
| `(status, created_at)` on payouts | Beat task finding stuck payouts |

### Why `TIMESTAMPTZ` everywhere

`TIMESTAMPTZ` (timestamp with time zone) stores in UTC and converts to local time on read. Using `TIMESTAMP` without timezone means ambiguous times during DST transitions — an unacceptable risk in a financial system.

---

## 13. API Reference

### `POST /api/v1/payouts/`

```
Headers:
  Idempotency-Key: <uuid-v4>      required — safe retry key
  X-Merchant-Id:   <uuid>         required — identifies merchant
  Content-Type:    application/json

Body:
  { "amount_paise": 50000, "bank_account_id": "<uuid>" }

Responses:
  201 Created         — new payout created, Celery task enqueued
  200 OK              — idempotent replay, cached response returned
  400 Bad Request     — validation failure
  402 Payment Required — insufficient funds
  409 Conflict        — idempotency key reused with different params
```

### `GET /api/v1/balance/?merchant_id=<uuid>`

```json
{
  "available_balance_paise": 950000,
  "held_balance_paise": 50000,
  "total_balance_paise": 1000000,
  "available_balance_inr": "₹9500.00",
  "held_balance_inr": "₹500.00",
  "total_balance_inr": "₹10000.00"
}
```

`_inr` fields are **display-only**. Never use them in business logic.

### `GET /api/v1/ledger/?merchant_id=<uuid>`

Full immutable audit trail. Every money event, in order, forever.

### `GET /api/v1/payouts/?merchant_id=<uuid>&status=<status>`

Paginated payout history with attempt counts, failure reasons, bank reference IDs.

---

## 14. What Deliberately Does Not Exist

These are architectural decisions, not missing features:

| Missing | Why it's missing |
|---------|-----------------|
| `balance` column on Merchant | Would create a second source of truth. `SUM(ledger)` is always correct. |
| `DECIMAL` type for amounts | `BIGINT` paise is exact. `DECIMAL` has rounding edge cases at scale. |
| Balance computed in Python | `sum(e.amount for e in entries)` skips the DB lock — race condition reintroduced. |
| `ATOMIC_REQUESTS = True` | Wraps every HTTP request in one transaction, holding locks for the entire request lifecycle including serialisation. |
| Optimistic locking | Pushes retry logic to application layer, re-enters the race window. |
| `payout.status = 'completed'` (direct assignment) | Bypasses the state machine. Always use `transition_to()`. |
| `LedgerEntry.objects.update(...)` | Entries are immutable. No update path exists by design. |

---

## 15. Production Deployment

### Live deployment

| Service | URL |
|---------|-----|
| Backend API | `https://payfintech-production.up.railway.app` |
| Frontend Dashboard | Vercel (see deployment) |

### Infrastructure

```
Railway:
  ├── web service       (Django + Gunicorn + Celery worker+beat)
  ├── PostgreSQL 14     (managed, persistent)
  └── Redis             (Celery broker)

Vercel:
  └── frontend          (React static build, CDN-served)
```

### Environment variables

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django signing key |
| `DEBUG` | `False` in production |
| `DB_*` | PostgreSQL connection |
| `REDIS_URL` | Celery broker |
| `ALLOWED_HOSTS` | Django host validation |
| `CORS_ALLOWED_ORIGINS` | Restricts which origins can call the API |
| `PAYOUT_BANK_FAILURE_RATE` | Simulated bank failure rate (0.0–1.0) |

### What's needed for real production

- [ ] Authentication (JWT or API keys per merchant)
- [ ] Rate limiting per merchant
- [ ] Bank account verification (penny drop via Razorpay/Cashfree)
- [ ] Real bank API integration (Razorpay X, Cashfree Payouts, etc.)
- [ ] Sentry for error tracking
- [ ] PagerDuty or similar for payout SLA alerting
- [ ] Separate Celery worker and beat services (currently co-located for free-tier constraint)
- [ ] Read replica for balance/ledger queries

---

## 16. Glossary

| Term | Definition |
|------|-----------|
| **Paise** | Smallest unit of Indian Rupee. ₹1 = 100 paise. All amounts stored as paise. |
| **Ledger entry** | Immutable record of a money event. Positive = credit, negative = debit. |
| **Payout hold** | Ledger debit created when payout is requested. Reserves funds. |
| **Payout release** | Ledger credit that cancels a hold — created on failure or completion. |
| **SELECT FOR UPDATE** | PostgreSQL row-level lock. Second writer blocks until first commits. |
| **Idempotency key** | Client-generated UUID ensuring a request produces the same result on retry. |
| **State machine** | Strict graph of allowed payout status transitions. All others raise an exception. |
| **Beat** | Celery's periodic task scheduler. Runs `recover_stuck_payouts` every 30s. |
| **acks_late** | Celery setting: task message not removed from queue until task completes. |
| **Terminal state** | A payout status with no valid outgoing transitions. `completed` and `failed`. |

---

*Every decision in this system was made to keep money correct — not convenient, not fast, not clever. Correct.*
