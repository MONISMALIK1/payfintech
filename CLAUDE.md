# CLAUDE.md — Payout Engine

> Fintech-grade payout system for Indian merchants receiving international payments.
> Built with Django + DRF · PostgreSQL · Celery · Redis · React + Tailwind.
> **Correctness over speed. Determinism over convenience.**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Database Schema](#4-database-schema)
5. [Core Design Decisions](#5-core-design-decisions)
6. [API Reference](#6-api-reference)
7. [State Machine](#7-state-machine)
8. [Celery Tasks](#8-celery-tasks)
9. [Money Integrity Rules](#9-money-integrity-rules)
10. [Concurrency Model](#10-concurrency-model)
11. [Idempotency Model](#11-idempotency-model)
12. [Retry & Recovery Logic](#12-retry--recovery-logic)
13. [Frontend Dashboard](#13-frontend-dashboard)
14. [Setup & Running Locally](#14-setup--running-locally)
15. [Environment Variables](#15-environment-variables)
16. [Edge Cases & Invariants](#16-edge-cases--invariants)
17. [What NOT to Do](#17-what-not-to-do)

---

## 1. Project Overview

This system enables merchants to:
- Receive international payments (credited to their ledger)
- Request withdrawals (payouts) to Indian bank accounts
- Track payout status in real time

**Key constraints that drive every design decision:**
- All amounts stored as `BIGINT` in **paise** (₹1 = 100 paise). No floats. Ever.
- Balance is never stored — always derived from `SUM(ledger_entries.amount_paise)`
- Every money operation is wrapped in a DB transaction
- Concurrency is handled via `SELECT FOR UPDATE` — not optimistic locking
- Idempotency is enforced at the DB level, scoped per merchant

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Dashboard                          │
│          (Balance · Ledger · Payout History · Form)             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / polling (3s)
┌──────────────────────────▼──────────────────────────────────────┐
│                     Django REST Framework                        │
│                                                                  │
│  POST /api/v1/payouts          ← Idempotency-Key header          │
│  GET  /api/v1/payouts/         ← payout history                  │
│  GET  /api/v1/balance/         ← available / held / total        │
│  GET  /api/v1/ledger/          ← all ledger entries              │
│  GET  /api/v1/merchants/       ← merchant list                   │
└──────────┬───────────────────────────────┬──────────────────────┘
           │                               │
           ▼                               ▼
┌──────────────────────┐      ┌────────────────────────┐
│     PostgreSQL        │      │    Redis (broker)       │
│                       │      └────────────┬───────────┘
│  merchants            │                   │
│  bank_accounts        │      ┌────────────▼───────────┐
│  ledger_entries  ◄────┼──────│    Celery Worker        │
│  payouts              │      │                         │
│  idempotency_records  │      │  process_payout task    │
└──────────────────────┘      │  recover_stuck_payouts  │
                               │  (beat, every 30s)      │
                               └─────────────────────────┘
```

### Request Flow — Happy Path

```
Client
  │
  ├─ POST /api/v1/payouts  { amount_paise, bank_account_id }
  │   Header: Idempotency-Key: <uuid>
  │
  ▼
[PayoutView]
  ├─ Check IdempotencyRecord → if hit, return cached response
  ├─ BEGIN TRANSACTION
  │   ├─ SELECT FOR UPDATE on ledger_entries (merchant lock)
  │   ├─ SUM(amount_paise) → available balance
  │   ├─ REJECT if insufficient funds
  │   ├─ INSERT payouts (status=pending)
  │   ├─ INSERT ledger_entries (type=payout_hold, amount=-X)
  │   └─ INSERT idempotency_records
  │   COMMIT
  │
  ├─ Enqueue Celery task: process_payout(payout_id)
  └─ Return 201 { payout_id, status: "pending", ... }

[Celery Worker — process_payout]
  ├─ BEGIN TRANSACTION
  │   ├─ SELECT FOR UPDATE on payout row
  │   ├─ transition_to("processing")  ← state machine enforced
  │   └─ COMMIT
  │
  ├─ Call simulated bank API
  │
  ├─ On SUCCESS:
  │   └─ BEGIN TRANSACTION
  │       ├─ SELECT FOR UPDATE on payout
  │       ├─ transition_to("completed")
  │       ├─ INSERT ledger_entry (type=payout_completed, amount=-X)
  │       └─ COMMIT
  │
  └─ On FAILURE:
      └─ Retry with backoff (max 3 attempts)
          └─ After max retries:
              BEGIN TRANSACTION
              ├─ transition_to("failed")
              ├─ INSERT ledger_entry (type=payout_release, amount=+X)
              └─ COMMIT  ← funds restored atomically
```

---

## 3. Directory Structure

```
payout-engine/
├── CLAUDE.md                          ← you are here
│
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   │
│   ├── config/
│   │   ├── __init__.py                ← imports celery app
│   │   ├── settings.py                ← all configuration
│   │   ├── urls.py                    ← root URL routing
│   │   └── celery.py                  ← Celery app + beat schedule
│   │
│   └── apps/
│       ├── accounts/                  ← Merchant + BankAccount models
│       │   ├── models.py
│       │   ├── views.py
│       │   ├── urls.py
│       │   ├── apps.py
│       │   └── __init__.py
│       │
│       ├── ledger/                    ← Immutable ledger + balance logic
│       │   ├── models.py              ← LedgerEntry, LedgerEntryType
│       │   ├── views.py               ← BalanceView, LedgerEntriesView
│       │   ├── urls.py
│       │   ├── apps.py
│       │   └── __init__.py
│       │
│       └── payouts/                   ← Payout lifecycle
│           ├── models.py              ← Payout, IdempotencyRecord, state machine
│           ├── service.py             ← create_payout(), all business logic
│           ├── tasks.py               ← Celery tasks
│           ├── views.py               ← PayoutView, PayoutDetailView
│           ├── serializers.py
│           ├── exceptions.py          ← custom DRF exception handler
│           ├── urls.py
│           ├── apps.py
│           └── __init__.py
│
└── frontend/
    ├── index.html
    ├── package.json
    └── src/
        ├── App.jsx
        ├── components/
        │   ├── BalanceCard.jsx
        │   ├── LedgerTable.jsx
        │   ├── PayoutHistory.jsx
        │   └── PayoutForm.jsx
        └── hooks/
            └── usePolling.js
```

---

## 4. Database Schema

### `merchants`
```sql
CREATE TABLE merchants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(254) UNIQUE NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### `bank_accounts`
```sql
CREATE TABLE bank_accounts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id          UUID NOT NULL REFERENCES merchants(id),
    account_holder_name  VARCHAR(255) NOT NULL,
    account_number       VARCHAR(20) NOT NULL,   -- encrypt at rest in prod
    ifsc_code            VARCHAR(11) NOT NULL,
    account_type         VARCHAR(10) DEFAULT 'savings',
    is_verified          BOOLEAN DEFAULT FALSE,
    is_primary           BOOLEAN DEFAULT FALSE,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON bank_accounts(merchant_id, is_primary);
```

### `ledger_entries` — The Core Table
```sql
CREATE TABLE ledger_entries (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id      UUID NOT NULL REFERENCES merchants(id),

    -- BIGINT in paise. Positive = credit. Negative = debit. Never zero.
    amount_paise     BIGINT NOT NULL CHECK (amount_paise != 0),

    entry_type       VARCHAR(30) NOT NULL,  -- see LedgerEntryType enum
    payout_id        UUID REFERENCES payouts(id),
    description      TEXT DEFAULT '',
    idempotency_key  VARCHAR(100) UNIQUE NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX ON ledger_entries(merchant_id, created_at DESC);
CREATE INDEX ON ledger_entries(merchant_id, entry_type);
CREATE INDEX ON ledger_entries(payout_id);

-- Balance query (used constantly):
-- SELECT SUM(amount_paise) FROM ledger_entries WHERE merchant_id = $1
```

**Balance formulas (always at DB level):**
```sql
-- Total balance (includes held funds):
SELECT SUM(amount_paise) FROM ledger_entries WHERE merchant_id = $1;

-- Held balance (active holds minus releases):
SELECT ABS(LEAST(SUM(amount_paise), 0))
FROM ledger_entries
WHERE merchant_id = $1
  AND entry_type IN ('payout_hold', 'payout_release');

-- Available balance = total - held
```

### `payouts`
```sql
CREATE TABLE payouts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id           UUID NOT NULL REFERENCES merchants(id),
    bank_account_id       UUID NOT NULL REFERENCES bank_accounts(id),

    -- BIGINT in paise. Always positive (represents requested amount).
    amount_paise          BIGINT NOT NULL CHECK (amount_paise > 0),

    status                VARCHAR(15) NOT NULL DEFAULT 'pending',
                          -- ENUM: pending | processing | completed | failed

    idempotency_key       VARCHAR(100) NOT NULL,
    attempt_count         INT DEFAULT 0,
    max_attempts          INT DEFAULT 3,

    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    failed_at             TIMESTAMPTZ,

    failure_reason        TEXT DEFAULT '',
    bank_reference_id     VARCHAR(100) DEFAULT ''
);

CREATE INDEX ON payouts(merchant_id, status);
CREATE INDEX ON payouts(status, created_at);
CREATE INDEX ON payouts(merchant_id, idempotency_key);
```

### `idempotency_records`
```sql
CREATE TABLE idempotency_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id      UUID NOT NULL REFERENCES merchants(id),
    idempotency_key  VARCHAR(100) NOT NULL,
    response_body    JSONB NOT NULL,       -- full response cached
    http_status_code INT DEFAULT 200,
    created_at       TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (merchant_id, idempotency_key)  -- scoped per merchant
);

CREATE INDEX ON idempotency_records(merchant_id, idempotency_key, created_at);
```

### Ledger Entry Types
| Type               | Sign | Meaning                                         |
|--------------------|------|-------------------------------------------------|
| `payment_received` | `+`  | Funds credited to merchant from incoming payment |
| `payout_hold`      | `−`  | Funds reserved when payout is requested         |
| `payout_release`   | `+`  | Hold reversed when payout fails                 |
| `payout_completed` | `−`  | Final debit when payout settles at bank         |
| `fee_debit`        | `−`  | Platform fee deducted                           |
| `adjustment_credit`| `+`  | Manual credit (e.g. dispute resolution)         |
| `adjustment_debit` | `−`  | Manual debit                                    |

---

## 5. Core Design Decisions

### Why no balance column?

A `balance` column creates a second source of truth. Under concurrent writes, keeping it in sync requires either:
- Application-level locking (fragile, doesn't survive crashes), or
- A trigger (hidden logic, hard to test)

`SUM(ledger_entries.amount_paise)` is always correct. It's one source. It's auditable. PostgreSQL can compute it fast with a partial index on `merchant_id`.

### Why BIGINT paise and not DECIMAL(12,2)?

- `BIGINT` arithmetic in PostgreSQL is exact and deterministic
- `DECIMAL` operations can still produce rounding surprises in edge cases
- Paise are indivisible — storing them as integers makes the invariant explicit
- Max `BIGINT`: ₹92 trillion — enough for any realistic scenario

### Why SELECT FOR UPDATE instead of optimistic locking?

For financial systems, **pessimistic locking is correct**. Optimistic locking (version counters) requires retry logic at the application layer, which re-introduces the race condition window. `SELECT FOR UPDATE` serializes at the database — the second concurrent writer blocks until the first commits, then reads the updated balance and correctly fails.

### Why manual transaction management (`ATOMIC_REQUESTS = False`)?

Django's `ATOMIC_REQUESTS` wraps every HTTP request in one transaction. That's too coarse — it means a long request holds locks for its entire duration. We open transactions only where needed, for the shortest possible duration, releasing locks as soon as the critical section completes.

---

## 6. API Reference

### `POST /api/v1/payouts`

Create a payout request.

**Required Headers:**
```
Idempotency-Key: <uuid-v4>       # e.g. "550e8400-e29b-41d4-a716-446655440000"
X-Merchant-Id: <merchant-uuid>   # identifies the requesting merchant
Content-Type: application/json
```

**Request Body:**
```json
{
  "amount_paise": 50000,
  "bank_account_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**Responses:**

`201 Created` — payout created:
```json
{
  "id": "...",
  "status": "pending",
  "amount_paise": 50000,
  "amount_inr": "₹500.00",
  "bank_account_id": "...",
  "idempotency_key": "550e8400-...",
  "created_at": "2024-01-15T10:30:00Z"
}
```

`200 OK` — idempotent replay (same key, same merchant, within 24h):
```json
{ ...exact same body as original 201... }
```

`402 Payment Required` — insufficient funds:
```json
{
  "error": "insufficient_funds",
  "message": "Available: 30000 paise. Requested: 50000 paise.",
  "available_paise": 30000
}
```

`400 Bad Request` — validation failure:
```json
{ "error": "validation_error", "message": "amount_paise must be a positive integer." }
```

`409 Conflict` — duplicate idempotency key on a different request body:
```json
{ "error": "idempotency_conflict", "message": "Key used with different parameters." }
```

---

### `GET /api/v1/payouts/`

List payouts for a merchant.

**Query params:** `merchant_id`, `status` (optional filter), `limit` (default 50), `offset`

**Response:**
```json
{
  "count": 12,
  "results": [
    {
      "id": "...",
      "status": "completed",
      "amount_paise": 50000,
      "amount_inr": "₹500.00",
      "bank_account": { "id": "...", "account_number_masked": "XXXX4321", "ifsc_code": "HDFC0001234" },
      "attempt_count": 1,
      "created_at": "...",
      "completed_at": "...",
      "bank_reference_id": "BANK_REF_XYZ"
    }
  ]
}
```

---

### `GET /api/v1/balance/`

**Query params:** `merchant_id`

**Response:**
```json
{
  "merchant_id": "...",
  "available_balance_paise": 150000,
  "held_balance_paise": 50000,
  "total_balance_paise": 200000,
  "available_balance_inr": "₹1500.00",
  "held_balance_inr": "₹500.00",
  "total_balance_inr": "₹2000.00"
}
```

> ⚠️ The `_inr` fields are for **display only**. Never use them in business logic.

---

### `GET /api/v1/ledger/`

**Query params:** `merchant_id`, `limit`, `offset`

**Response:**
```json
{
  "count": 47,
  "results": [
    {
      "id": "...",
      "entry_type": "payout_hold",
      "amount_paise": -50000,
      "amount_inr": "₹500.00",
      "direction": "debit",
      "description": "Hold for payout abc123",
      "payout_id": "...",
      "created_at": "..."
    }
  ]
}
```

---

### `GET /api/v1/merchants/`

List all merchants (dev/admin use). Returns `id`, `name`, `email`, `bank_accounts`.

---

## 7. State Machine

```
                    ┌─────────┐
                    │ PENDING │  ← created on POST /payouts
                    └────┬────┘
                         │ Celery picks up task
                         ▼
                  ┌─────────────┐
                  │ PROCESSING  │  ← bank API call in progress
                  └──────┬──────┘
              ┌──────────┴──────────┐
              │                     │
        bank success           bank failure
              │                     │
              ▼                     ▼
        ┌──────────┐         ┌────────┐
        │COMPLETED │         │ FAILED │  ← funds released to ledger
        └──────────┘         └────────┘
         (terminal)           (terminal)
```

**All transitions are validated in `Payout.transition_to(new_status)`.**

Any attempt to transition outside the allowed graph raises `InvalidStateTransitionError`. This is enforced:
- In the Celery task before saving
- At the `save()` level via `clean()` in production hardening

**Invalid transition examples that MUST be rejected:**
- `pending → completed` (skipping processing)
- `completed → failed` (reversing terminal state)
- `failed → processing` (cannot retry a failed payout; create new one)

---

## 8. Celery Tasks

### `process_payout(payout_id: str)`

Located in `apps/payouts/tasks.py`.

```
1. Load payout with SELECT FOR UPDATE
2. Validate: still in 'pending' state (guard against duplicate task dispatch)
3. transition_to('processing') + save  →  COMMIT
4. Call simulated bank API (random success/failure)
5a. SUCCESS:
    BEGIN TX
      transition_to('completed')
      INSERT ledger_entry(type='payout_completed', amount=-X)
    COMMIT
5b. FAILURE:
    IF can_retry:
        raise exception → Celery retries with countdown backoff
    ELSE:
        BEGIN TX
          transition_to('failed')
          INSERT ledger_entry(type='payout_release', amount=+X)
        COMMIT
```

**Retry configuration:**
```python
@app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(BankAPIError,),
    retry_backoff=True,           # Celery exponential backoff
    retry_backoff_max=90,         # cap at 90 seconds
    acks_late=True,               # don't ack until task completes
)
```

Manual countdown schedule from `settings.py`:
```python
PAYOUT_RETRY_COUNTDOWN_SECONDS = [10, 30, 90]  # attempt 1, 2, 3
```

---

### `recover_stuck_payouts()` — Beat task, runs every 30s

Finds payouts stuck in `processing` for longer than `PAYOUT_PROCESSING_TIMEOUT_SECONDS` (default: 30s) and re-enqueues `process_payout` for them.

This handles:
- Worker crash mid-task
- Redis broker restart
- Network partition between worker and DB

```python
stuck = Payout.objects.filter(
    status='processing',
    processing_started_at__lt=cutoff,
    attempt_count__lt=F('max_attempts')
)
for payout in stuck:
    process_payout.delay(str(payout.id))
```

---

## 9. Money Integrity Rules

These are non-negotiable. Any code that violates them must be rejected in review.

| Rule | Rationale |
|------|-----------|
| All amounts stored as `BIGINT` paise | Eliminates float rounding entirely |
| No `balance` column anywhere | Single source of truth = ledger |
| Balance = `SUM(ledger_entries.amount_paise)` | Computed at DB level only |
| No Python arithmetic on paise values | Python floats are IEEE 754 — unsafe |
| Every ledger entry is immutable | Audit trail, no retroactive edits |
| Ledger entries are never deleted | `on_delete=PROTECT` on all FK refs |
| Funds hold precedes any state save | Atomic — payout + hold created together |
| Refund is atomic with failure state | Can't mark failed without releasing funds |
| No zero-amount ledger entries | Checked via `CHECK (amount_paise != 0)` |
| Idempotency key on every ledger entry | Prevents duplicate entries on retry |

---

## 10. Concurrency Model

### The Double-Spend Scenario

```
Merchant has ₹100 (10,000 paise)

Request A: payout ₹60 (6,000 paise)
Request B: payout ₹60 (6,000 paise)

Both arrive simultaneously.
```

**Without locking:** Both read balance=10,000, both pass the check, both create holds.
Merchant ends up with -₹20. ❌

**With SELECT FOR UPDATE:**
```
Transaction A:                        Transaction B:
  SELECT FOR UPDATE                     SELECT FOR UPDATE
  (acquires lock)                       (BLOCKS — waiting)
  balance = 10,000 ✓
  CREATE payout A
  INSERT hold -6,000
  COMMIT
  (releases lock)
                                        (unblocked)
                                        balance = 4,000
                                        4,000 < 6,000 → REJECT ✓
```

Result: A succeeds, B fails with `InsufficientFundsError`. Correct. ✅

### Lock Scope

The lock is on **all ledger entries for a given merchant_id**:
```python
LedgerEntry.objects.select_for_update().filter(merchant_id=merchant_id).values('id')
```

This means two concurrent payouts from the same merchant are serialized. Two concurrent payouts from *different* merchants are fully parallel — no cross-merchant contention.

---

## 11. Idempotency Model

### Scope

Idempotency is scoped per `(merchant_id, idempotency_key)`. Different merchants may use the same key without conflict.

### Window

24 hours, enforced at query time:
```python
window_start = timezone.now() - timedelta(hours=PAYOUT_IDEMPOTENCY_WINDOW_HOURS)
existing = IdempotencyRecord.objects.filter(
    merchant_id=merchant_id,
    idempotency_key=key,
    created_at__gte=window_start,
).first()
```

### What gets cached

The full HTTP response body (JSON) and status code. A replay returns byte-for-byte identical responses.

### Race condition on first insert

Two concurrent requests with the same key race to insert the `IdempotencyRecord`. The second will hit the `UNIQUE (merchant_id, idempotency_key)` constraint and get an `IntegrityError`, which is caught and converted to a 200 replay response.

### Client requirements

Clients MUST:
- Send `Idempotency-Key: <uuid-v4>` on every `POST /api/v1/payouts`
- Use a new UUID for each distinct payout intent
- Reuse the same UUID when retrying a failed/timed-out request

---

## 12. Retry & Recovery Logic

### Normal retry flow (within task)

```
Attempt 1 fails → wait 10s → Attempt 2
Attempt 2 fails → wait 30s → Attempt 3
Attempt 3 fails → mark FAILED + release funds
```

### Stuck recovery (beat task)

Triggered when `processing_started_at` is older than 30 seconds. Handles worker crash scenarios. The task re-enqueues `process_payout` — which will:
1. Load the payout
2. See it's `processing` (not `pending`) — skip to bank call
3. OR if `attempt_count >= max_attempts` → mark failed + release

### Refund atomicity

The refund (payout_release) and state change (failed) happen in the same DB transaction. If the worker crashes after writing `failed` but before writing the release, the idempotency key on the ledger entry prevents a duplicate release on the next recovery run.

```python
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(id=payout_id)
    payout.transition_to(PayoutStatus.FAILED)
    payout.failure_reason = reason
    payout.save()

    LedgerEntry.objects.create(
        merchant=payout.merchant,
        amount_paise=+payout.amount_paise,   # positive = refund
        entry_type=LedgerEntryType.PAYOUT_RELEASE,
        payout=payout,
        idempotency_key=f"release-{payout.id}",  # stable key for deduplication
        description=f"Refund for failed payout {payout.id}",
    )
```

---

## 13. Frontend Dashboard

Built with React + Tailwind CSS. Polling interval: 3 seconds.

### Components

**`BalanceCard`** — three panels:
- Available balance (green) — funds free to withdraw
- Held balance (amber) — funds reserved in pending/processing payouts
- Total balance (neutral) — available + held

**`PayoutForm`** — form to request a payout:
- Amount input (INR, converted to paise before POST)
- Bank account selector
- Generates UUID idempotency key on submit
- Shows live status after submission

**`PayoutHistory`** — table of payouts with:
- Status badge (color-coded: pending=gray, processing=blue, completed=green, failed=red)
- Amount, bank account (masked), timestamps
- Attempt count / failure reason on failure

**`LedgerTable`** — scrollable ledger with:
- Entry type, direction (credit/debit), amount, timestamp
- Color-coded rows

### Polling Strategy

```javascript
// usePolling.js
useEffect(() => {
  const interval = setInterval(() => {
    fetchBalance();
    fetchPayouts();
    fetchLedger();
  }, 3000);
  return () => clearInterval(interval);
}, [merchantId]);
```

No WebSocket complexity — polling every 3s is sufficient for payout status updates. The backend is stateless and each poll is a cheap read.

---

## 14. Setup & Running Locally

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Redis 6+
- Node.js 18+ (for frontend)

### Backend

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set DB_NAME, DB_USER, DB_PASSWORD, REDIS_URL

# Run migrations
python manage.py migrate

# Create a test merchant + seed data
python manage.py shell < scripts/seed.py

# Start Django dev server
python manage.py runserver 8000

# Start Celery worker (separate terminal)
celery -A config worker --loglevel=info --concurrency=4

# Start Celery beat scheduler (separate terminal)
celery -A config beat --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
npm run dev       # starts on http://localhost:5173
```

### Docker Compose (recommended)

```bash
docker compose up --build
```

Services: `db` (PostgreSQL), `redis`, `backend`, `worker`, `beat`, `frontend`

---

## 15. Environment Variables

| Variable                          | Default            | Description                        |
|-----------------------------------|--------------------|------------------------------------|
| `SECRET_KEY`                      | (dev key)          | Django secret key                  |
| `DEBUG`                           | `True`             | Debug mode                         |
| `DB_NAME`                         | `payout_engine`    | PostgreSQL database name           |
| `DB_USER`                         | `postgres`         | PostgreSQL user                    |
| `DB_PASSWORD`                     | `postgres`         | PostgreSQL password                |
| `DB_HOST`                         | `localhost`        | PostgreSQL host                    |
| `DB_PORT`                         | `5432`             | PostgreSQL port                    |
| `REDIS_URL`                       | `redis://localhost:6379/0` | Redis connection URL    |
| `PAYOUT_IDEMPOTENCY_WINDOW_HOURS` | `24`               | Idempotency key TTL in hours       |
| `PAYOUT_MAX_RETRIES`              | `3`                | Max Celery task retries            |
| `PAYOUT_PROCESSING_TIMEOUT_SECONDS` | `30`            | Stuck-in-processing threshold (s)  |

---

## 16. Edge Cases & Invariants

| Scenario | Behavior |
|----------|----------|
| Two ₹60 requests, ₹100 balance, concurrent | First succeeds, second gets `402 InsufficientFunds` |
| Same idempotency key sent twice | Second returns cached `200` with original response body |
| Worker crashes mid-processing | Beat task re-enqueues after 30s |
| Bank API times out on attempt 3 | Payout marked `failed`, funds released atomically |
| Payout already `completed`, task fires again | `select_for_update` + state check → no-op, logged |
| Ledger entry insert fails after payout created | Transaction rolls back entire payout creation |
| Merchant not found / inactive | `400 PayoutValidationError` before any DB writes |
| Bank account not owned by merchant | `400 PayoutValidationError` |
| `amount_paise = 0` | Rejected at API layer before DB touch |
| `amount_paise` is float (e.g. `499.99`) | DRF IntegerField rejects it at deserialization |
| DB goes down mid-transaction | Connection error propagates, no partial writes |

---

## 17. What NOT to Do

These are common mistakes that MUST be avoided in this codebase:

```python
# ❌ NEVER — float arithmetic on money
balance = payout.amount_paise / 100  # use only for display formatting

# ❌ NEVER — store balance as a column
merchant.balance -= amount_paise
merchant.save()

# ❌ NEVER — compute balance in Python
entries = LedgerEntry.objects.filter(merchant=merchant)
balance = sum(e.amount_paise for e in entries)  # use DB SUM()

# ❌ NEVER — transition state without SELECT FOR UPDATE
payout.status = 'completed'
payout.save()  # race condition — concurrent writes possible

# ❌ NEVER — create ledger entry outside a transaction
LedgerEntry.objects.create(...)  # must be inside with transaction.atomic()

# ❌ NEVER — delete or update ledger entries
LedgerEntry.objects.filter(...).update(amount_paise=...)  # immutable!

# ❌ NEVER — skip idempotency key on ledger entries
LedgerEntry.objects.create(amount_paise=X, ...)  # must include idempotency_key

# ❌ NEVER — allow transition outside state machine
payout.status = 'completed'  # use payout.transition_to('completed')

# ❌ NEVER — use Django's ATOMIC_REQUESTS=True for payout views
# It holds locks for the entire request lifecycle including serialization

# ❌ NEVER — use Decimal for intermediate calculations
from decimal import Decimal
fee = Decimal(amount_paise) * Decimal('0.02')  # keep everything in paise integers
fee_paise = int(amount_paise * 2) // 100  # integer arithmetic only
```

---

## Glossary

| Term | Definition |
|------|-----------|
| **Paise** | Smallest unit of Indian Rupee. ₹1 = 100 paise. All amounts stored in paise. |
| **Ledger entry** | Immutable record of a money event. Credits (+), debits (−). |
| **Payout hold** | Ledger debit created when payout is requested. Reserves funds. |
| **Payout release** | Ledger credit created when payout fails. Returns held funds. |
| **Idempotency key** | Client-generated UUID ensuring safe request retries. |
| **SELECT FOR UPDATE** | PostgreSQL row-level lock preventing concurrent reads during a transaction. |
| **State machine** | Strict set of allowed payout status transitions. All others are illegal. |
| **Beat** | Celery's periodic task scheduler. Runs `recover_stuck_payouts` every 30s. |

---

*This document should be updated whenever the schema, API contract, state machine, or money rules change. Treat it as a living spec.*
