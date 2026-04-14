# Tiketi Smart Contracts

Three focused Solidity contracts on Base L2. Each handles one financial responsibility.

## Architecture

```
StakeEscrow.sol    — vendor stake deposits, 30-day timelock, 15% slash
PayoutVault.sol    — fan ticket payments, T+48h vendor payout, pull refunds
BuybackPool.sol    — buyback refunds, resale 40/60 split, self-funding circuit
```

## Money Circuit (v5)

### Scenario A — Normal sale
```
Fan pays $100 → PayoutVault.deposit()
T+48h → vendor calls claimPayout() → $98 net, $2 fee to treasury
```

### Scenario B — Buyback + resale
```
Fan pays $100  → PayoutVault.deposit()
Event sells out (100% stock) → buyback window opens
Fan returns    → BuybackPool.requestBuyback()
                 └→ calls PayoutVault.markReturned() → $100 moves to BuybackPool
                 └→ BuybackPool.refund() → $90 to fan, $10 to treasury
                 └→ vendor claimable zeroed (no double-claim)
New buyer $110 → BuybackPool.depositResale() → $44 treasury, $66 vendor (immediate)

Platform net: -$90 + $10 + $44 = -$36  (intentional risk, only on sold-out events)
Vendor net:   $66 (relist only)
```

### Scenario C — Buyback, no resale (worst case)
```
Platform net: -$80 ($10 retention, $90 refund, no resale)
Mitigated by: buyback only activates at 100% sold-out
```

### Scenario D — Cancellation
```
Platform calls PayoutVault.setRefundable(eventId)   → O(1) gas
Django enqueues per-fan Celery tasks
Each task calls PayoutVault.claimRefund()            → 100% to fan
No gas ceiling — works for 100 or 100,000 tickets
```

## Contract Functions

### StakeEscrow
| Function | Caller | Description |
|---|---|---|
| `stake(tier)` | Vendor | Deposit $110/$220 USDC |
| `requestExit()` | Vendor | Start 30-day timelock |
| `claimStake()` | Vendor | Withdraw after timelock |
| `slash(vendor, reason)` | Owner | 15% penalty to treasury |
| `forceMajeure(vendor, reason)` | Owner | No slash on admin cancel |

### PayoutVault
| Function | Caller | Description |
|---|---|---|
| `setKickoff(eventId, ts, vendor)` | Owner | Register event (immutable) |
| `deposit(eventId, ticketId, fan, amount)` | Owner | Fan payment in |
| `markReturned(eventId, ticketId)` | BuybackPool | Zero vendor claimable, transfer deposit |
| `claimPayout(eventId)` | Vendor | Claim after T+48h |
| `setRefundable(eventId)` | Owner | Unlock cancellation claims |
| `claimRefund(eventId, ticketId)` | Owner | Per-fan Django-initiated |
| `refundOne(ticketId)` | Owner | Postpone opt-out (100%) |

### BuybackPool
| Function | Caller | Description |
|---|---|---|
| `receiveDeposit(ticketId, amount, fan)` | PayoutVault | Accept transferred deposit |
| `requestBuyback(eventId, ticketId, fan, type)` | Owner | Full buyback circuit |
| `depositResale(ticketId, amount, vendor, buyer)` | Owner | Accept $110 + distribute 40/60 |
| `recordReturn(ticketId)` | Owner | On-chain proof emission |
| `fundPool(amount)` | Owner | Top up float buffer |

## Setup

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Install dependencies (OpenZeppelin if needed)
cd contracts
forge build
```

## Running Tests

```bash
# All tests
forge test -vvv

# Single contract
forge test --match-contract StakeEscrowTest -vvv
forge test --match-contract PayoutVaultTest -vvv
forge test --match-contract BuybackPoolTest -vvv

# Single test
forge test --match-test test_full_circuit_single_ticket_90_percent_refund -vvv

# With gas report
forge test --gas-report

# Fuzz with more runs
forge test --fuzz-runs 10000
```

## Deployment

```bash
# Copy and fill env
cp .env.example .env

# Deploy to Base Sepolia (testnet)
forge script script/Deploy.s.sol \
  --rpc-url base_sepolia \
  --broadcast \
  --verify \
  -vvvv

# Deploy to Base mainnet
forge script script/Deploy.s.sol \
  --rpc-url base \
  --broadcast \
  --verify \
  -vvvv
```

## Security Notes

- All financial functions are `nonReentrant`
- `markReturned()` is access-controlled to `BuybackPool` address only
- `receiveDeposit()` is access-controlled to `PayoutVault` address only
- Ownership uses two-step transfer pattern (see `Ownable.sol`)
- `deposit()` is idempotent — safe to retry on chain timeout
- `claimPayout()` vendor-gated by `msg.sender == e.vendor`
- CEI (Checks-Effects-Interactions) pattern throughout
- No ETH handling — USDC only via `IERC20`
