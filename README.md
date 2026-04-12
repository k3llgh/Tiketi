# Tiketi

**Africa's trust-minimized ticketing platform.**

Fraud-proof TOTP tickets. On-chain vendor accountability. Programmatic buybacks.
Built for East Africa, designed to scale across the continent.

---

## Architecture overview

```
Web2 (Django)               Web3 (Base L2)
─────────────────           ──────────────────────
State management      ←→    Value management
TOTP secrets               StakeEscrow.sol
Seat assignments           PayoutVault.sol
Event status machine       BuybackPool.sol
Gate logs
```

**Principle:** Database is the source of truth for state. Blockchain is the source of truth for value. Each layer fails independently.

## Quick start

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in: DB credentials, Paystack keys, AT keys, Base RPC, contract addresses

# 2. Start the stack
docker-compose up -d

# 3. Run migrations (django-tenants requires migrate_schemas)
docker-compose exec web python manage.py migrate_schemas --shared

# 4. Create a superuser
docker-compose exec web python manage.py createsuperuser

# 5. Open
# Web:          http://localhost
# Admin:        http://localhost/admin
# RabbitMQ UI:  http://localhost:15672  (tiketi / tiketi_dev_pass)
```

## Project structure

```
tiketi/
├── apps/
│   ├── accounts/      # Users, vendors, OTP auth, staking
│   ├── events/        # Event lifecycle, 7-state machine
│   ├── tickets/       # Purchase (FIFO), TOTP, group tickets
│   ├── wallet/        # USD balance (USDC display layer)
│   ├── buyback/       # Guard checks, refund, relist
│   ├── gate/          # TOTP validation, offline sync
│   ├── payments/      # Paystack webhooks
│   ├── notifications/ # SMS + email + 4 Celery tasks
│   ├── audit/         # Immutable event log
│   └── contracts/     # web3.py bridge to Base contracts
├── contracts/
│   ├── src/
│   │   ├── StakeEscrow.sol
│   │   ├── PayoutVault.sol
│   │   └── BuybackPool.sol
│   ├── test/          # Foundry test suite (60+ tests)
│   └── script/        # Deploy.s.sol
├── templates/         # Django templates + HTMX
├── config/            # Settings, URLs, Celery, WSGI
├── Dockerfile
├── docker-compose.yml
└── nginx.conf
```

## Key flows

### Fan purchases a ticket (4 clicks)
1. Browse events → tap match card
2. Modal opens → select Regular/VIP/VVIP + quantity (1–5)
3. Checkout → wallet or M-Pesa/card via on-ramp
4. Confirm → DB commit (status: `pending_payment`) → Celery enqueues `PayoutVault.deposit()`
5. On-chain confirm → status: `active` → SMS + email + in-app TOTP code

### Gate validation
Gate device syncs all active ticket secrets at start-of-day.
Staff enters 6-digit TOTP code → 3 checks (offline):
1. TOTP cryptographically valid (±30s)
2. Ticket status ∈ {active, resold}
3. Event kickoff date = today

Unlimited re-entry on event day. All scans logged to `TicketEntry`.

### Buyback + relist
Triggers when event reaches 100% original stock sold-out:
- `activate_relist` Celery task opens buyback window (one-way latch)
- Fan returns ticket → `BuybackPool.requestBuyback()` → 90%/80% refund
- `PayoutVault.markReturned()` transfers deposit to BuybackPool
- Vendor claimable zeroed — no double-claim possible
- Returned ticket relisted at 110% → new buyer pays → 40/60 split immediate

### Event cancellation
- **Vendor cancel**: 15% stake slash → `StakeEscrow.slash()` → `setRefundable()` → fan pull-claims
- **Admin cancel** (force majeure): no slash → `forceMajeure()` → `setRefundable()` → fan pull-claims
- Pull-over-push: Django enqueues per-fan `submit_claim_refund` Celery tasks after `setRefundable()`

## Celery tasks

| Task | Schedule | Responsibility |
|---|---|---|
| `void_stale_payments` | Every 2 min | `pending_payment` → `failed` after 10 min timeout |
| `activate_relist` | Triggered | Opens buyback window at 100% stock sold-out |
| `expire_tickets` | Daily 04:00 EAT | `returned/relisted` → `expired` post-event |
| `send_notifications` | Triggered | SMS + email for all events |

## Smart contracts (Base L2)

```bash
cd contracts
forge install foundry-rs/forge-std
forge test -vvv          # run full test suite
forge test --gas-report  # gas costs per function
```

Deploy:
```bash
cp .env.example .env  # fill BASE_RPC_URL, DEPLOYER_PRIVATE_KEY, TREASURY_ADDRESS
forge script script/Deploy.s.sol --rpc-url base_sepolia --broadcast --verify
```

## Environment variables

See `.env.example` for all required variables. Critical ones:

| Variable | Description |
|---|---|
| `PLATFORM_PRIVATE_KEY` | Hot wallet signing all contract txns — never commit |
| `STAKE_ESCROW_ADDRESS` | Set after contract deployment |
| `PAYOUT_VAULT_ADDRESS` | Set after contract deployment |
| `BUYBACK_POOL_ADDRESS` | Set after contract deployment |
| `PAYSTACK_SECRET_KEY` | Ticket payment processing |
| `AT_API_KEY` | Africa's Talking SMS |

## Revenue model

| Stream | Rate | Enforcement |
|---|---|---|
| Booking fee | 2% (min $0.25) | `PayoutVault.splitFee()` on vendor claim |
| Buyback retention | 10% single / 20% group | `BuybackPool.refund()` |
| Relist cut | 40% of 110% resale | `BuybackPool.depositResale()` |
| Withdrawal fee | 2% on cashout | Wallet service |

Vendor stake ($110/$220 USDC) is a **refundable deposit**, not a fee. Returned in full after clean 30-day exit. 15% slashed on vendor-caused cancellation.

## Production checklist

- [ ] Set `DEBUG=False` and strong `SECRET_KEY`
- [ ] Configure PostgreSQL with connection pooling (PgBouncer)
- [ ] Deploy contracts to Base mainnet, set addresses in `.env`
- [ ] Fund `BuybackPool` with initial USDC float
- [ ] Configure Cloudflare for subdomain routing (`*.tiketi.co`)
- [ ] Set up Sentry DSN for error tracking
- [ ] Configure Celery beat in database scheduler via admin
- [ ] Register gate devices and set `device_id` query params
- [ ] Run `python manage.py run_event_listener` as a separate process
- [ ] Set `LISTENER_START_BLOCK` to deployment block number
