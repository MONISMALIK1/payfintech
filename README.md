# Payout Engine

Fintech-grade payout system for Indian merchants receiving international payments.

**Stack:** Django + DRF · PostgreSQL · Celery · Redis · React + Tailwind

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 6+
- Node.js 18+ (for frontend)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DB credentials

# Run migrations
python manage.py migrate

# Seed test data (merchants with starting balance)
python manage.py shell < scripts/seed.py

# Start Django dev server
python manage.py runserver 8000

# In separate terminal: Start Celery worker
celery -A config worker --loglevel=info --concurrency=4

# In separate terminal: Start Celery beat scheduler
celery -A config beat --loglevel=info
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### Docker (Recommended)

```bash
docker compose up --build
```

---

## Running Tests

```bash
cd backend
pytest
```

### Run Specific Test Files

```bash
# Idempotency tests
pytest apps/payouts/tests/test_idempotency.py -v

# Concurrency tests
pytest apps/payouts/tests/test_concurrency.py -v

# State machine tests
pytest apps/payouts/tests/test_state_machine.py -v

# Ledger integrity tests
pytest apps/payouts/tests/test_ledger.py -v
```

### Test Database

Tests use a separate test database. Create it with:

```bash
createdb -U postgres payout_engine_test
```

Or set `TEST_DB_NAME` in your environment.

---

## API Endpoints

### Payouts

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/payouts/` | Create payout request |
| GET | `/api/v1/payouts/` | List payouts (query: `merchant_id`, `status`, `limit`, `offset`) |
| GET | `/api/v1/payouts/<id>/` | Get payout details |

**Required Headers for POST:**
```
Idempotency-Key: <uuid-v4>
X-Merchant-Id: <merchant-uuid>
Content-Type: application/json
```

**Request Body:**
```json
{
  "amount_paise": 50000,
  "bank_account_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

### Balance

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/balance/` | Get available/held/total balance |

**Query Params:** `merchant_id`

### Ledger

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/ledger/` | List ledger entries |

**Query Params:** `merchant_id`, `limit`, `offset`

### Merchants

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/merchants/` | List all merchants |

---

## Key Design Decisions

### Money Handling

- All amounts stored as `BIGINT` in **paise** (₹1 = 100 paise)
- No floats. Ever. Float division only for display formatting
- Balance is **never stored** — always computed as `SUM(ledger_entries.amount_paise)`

### Concurrency

- `SELECT FOR UPDATE` serializes payouts per merchant
- Prevents double-spend: two concurrent ₹60 requests with ₹100 balance → one succeeds, one fails

### Idempotency

- Client sends `Idempotency-Key: <uuid>` header
- Scoped per `(merchant_id, key)` with 24h window
- Replay returns byte-identical cached response

### State Machine

```
pending → processing → completed
                      → failed
```

Terminal states (completed, failed) cannot transition.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Dashboard                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / polling (3s)
┌──────────────────────────▼──────────────────────────────────────┐
│                     Django REST Framework                        │
│  POST /api/v1/payouts  │  GET /api/v1/balance/                  │
│  GET  /api/v1/payouts/ │  GET /api/v1/ledger/                   │
└──────────┬───────────────────────────────┬──────────────────────┘
           │                               │
           ▼                               ▼
┌──────────────────────┐      ┌────────────────────────┐
│     PostgreSQL        │      │    Celery Worker        │
│  - merchants          │      │  - process_payout       │
│  - bank_accounts      │      │  - recover_stuck        │
│  - ledger_entries     │      └─────────────────────────┘
│  - payouts            │
│  - idempotency_records│
└──────────────────────┘
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (dev key) | Django secret |
| `DEBUG` | `True` | Debug mode |
| `DB_NAME` | `payout_engine` | PostgreSQL database |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | `postgres` | PostgreSQL password |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `PAYOUT_IDEMPOTENCY_WINDOW_HOURS` | `24` | Idempotency key TTL |
| `PAYOUT_MAX_RETRIES` | `3` | Celery retry limit |
| `PAYOUT_PROCESSING_TIMEOUT_SECONDS` | `30` | Stuck payout threshold |
| `PAYOUT_BANK_FAILURE_RATE` | `0.2` | Simulated failure rate |

---

## Testing Idempotency

```bash
cd backend
pytest apps/payouts/tests/test_idempotency.py -v
```

**What it proves:**
1. Same key replay returns identical response (200, not 201)
2. No duplicate payout/ledger entries on replay
3. Same key with different params → 409 conflict
4. Concurrent same-key requests → exactly one creates payout
5. Same key across different merchants → allowed (scoped per merchant)

---

## Testing Concurrency

```bash
cd backend
pytest apps/payouts/tests/test_concurrency.py -v
```

**What it proves:**
1. Two concurrent ₹60 payouts with ₹100 balance → one succeeds, one fails
2. Ten concurrent payouts → only those within balance succeed
3. Different merchants don't block each other (lock scoped to merchant_id)
4. Balance never goes negative

---

## License

MIT
