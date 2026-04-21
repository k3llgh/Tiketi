// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";
import {ReentrancyGuard} from "./utils/ReentrancyGuard.sol";
import {Ownable} from "./utils/Ownable.sol";

/**
 * @title  PayoutVault
 * @notice Holds fan ticket payments in USDC until T+48h after event kickoff.
 *
 *  Purchase flow (normal):
 *    deposit(eventId, ticketId)  → fan payment locked per ticket
 *    claimPayout(eventId)        → vendor claims net amount at T+48h
 *                                  2% booking fee split to treasury on claim
 *
 *  Buyback flow:
 *    markReturned(ticketId)      → zeros vendor claimable for this ticket
 *                                  transfers deposit to BuybackPool.receiveDeposit()
 *
 *  Cancellation (pull-over-push, no gas ceiling):
 *    setRefundable(eventId)      → O(1) call, unlocks all fan claims
 *    claimRefund(eventId)        → each fan pulls own refund, Django-initiated
 *                                  per-fan Celery task, gas sponsored by paymaster
 *
 *  Postpone opt-out:
 *    refundOne(ticketId, fan)    → 100% refund for a single ticket
 *                                  called by platform within 48h opt-out window
 */
contract PayoutVault is ReentrancyGuard, Ownable {
    // ── Constants ──────────────────────────────────────────────────────────────

    uint256 public constant BOOKING_FEE_BPS = 200;   // 2%
    uint256 public constant BPS_DENOM       = 10_000;
    uint256 public constant PAYOUT_DELAY    = 48 hours;

    // ── Storage ────────────────────────────────────────────────────────────────

    IERC20  public immutable usdc;
    address public           treasury;
    address public           buybackPool;     // BuybackPool address — set after deploy

    struct EventConfig {
        uint256 kickoff;          // Unix timestamp set by Django on event creation
        address vendor;           // Vendor wallet address
        bool    refundable;       // True after setRefundable() — cancellation
        bool    payoutClaimed;    // True after claimPayout()
        uint256 vendorClaimable;  // Net USDC vendor can claim (decremented by markReturned)
        uint256 totalDeposited;   // Gross total deposited for accounting
    }

    struct TicketDeposit {
        uint256 amount;       // USDC deposited for this ticket
        address fan; // Fan who paid
        bytes32 eventId;
        bool    returned;     // True after markReturned()
        bool    refunded;     // True after claimRefund() or refundOne()
    }

    mapping(bytes32 => EventConfig)   public events;       // eventId → config
    mapping(bytes32 => TicketDeposit) public tickets;      // ticketId → deposit

    // ── Events ─────────────────────────────────────────────────────────────────

    event KickoffSet(bytes32 indexed eventId, uint256 kickoff, address vendor);
    event Deposited(bytes32 indexed eventId, bytes32 indexed ticketId, address fan, uint256 amount);
    event DepositTransferred(bytes32 indexed ticketId, uint256 amount, address buybackPool);
    event PayoutClaimed(bytes32 indexed eventId, address vendor, uint256 amount, uint256 fee);
    event RefundableSet(bytes32 indexed eventId);
    event RefundClaimed(bytes32 indexed eventId, address indexed fan, uint256 amount);
    event RefundedOne(bytes32 indexed ticketId, address indexed fan, uint256 amount);
    event BuybackPoolUpdated(address indexed newPool);
    event TreasuryUpdated(address indexed newTreasury);

    // ── Errors ─────────────────────────────────────────────────────────────────

    error EventNotConfigured();
    error KickoffAlreadySet();
    error TicketAlreadyDeposited();
    error TicketAlreadyReturned();
    error TicketAlreadyRefunded();
    error EventNotRefundable();
    error NoDepositFound();
    error PayoutAlreadyClaimed();
    error PayoutNotYetUnlocked(uint256 unlockAt);
    error KickoffNotSet();
    error BuybackPoolNotSet();
    error ZeroAddress();
    error NotBuybackPool();
    error ZeroAmount();

    // ── Constructor ────────────────────────────────────────────────────────────

    constructor(address _usdc, address _treasury) Ownable(msg.sender) {
        if (_usdc == address(0) || _treasury == address(0)) revert ZeroAddress();
        usdc     = IERC20(_usdc);
        treasury = _treasury;
    }

    // ── External — platform owner ──────────────────────────────────────────────

    /**
     * @notice Set the BuybackPool address. Called once after BuybackPool is deployed.
     */
    function setBuybackPool(address _pool) external onlyOwner {
        if (_pool == address(0)) revert ZeroAddress();
        buybackPool = _pool;
        emit BuybackPoolUpdated(_pool);
    }

    /**
     * @notice Register event kickoff timestamp and vendor address.
     *         Called by Django when a new event is created.
     *         Immutable once set — prevents timestamp manipulation.
     * @param eventId  bytes32 hash of the DB event UUID
     * @param kickoff  Unix timestamp of event kickoff
     * @param vendor   Vendor's smart wallet address
     */
    function setKickoff(bytes32 eventId, uint256 kickoff, address vendor)
        external
        onlyOwner
    {
        if (vendor == address(0)) revert ZeroAddress();
        if (kickoff == 0) revert ZeroAmount();
        EventConfig storage e = events[eventId];
        if (e.kickoff != 0) revert KickoffAlreadySet();

        e.kickoff = kickoff;
        e.vendor  = vendor;

        emit KickoffSet(eventId, kickoff, vendor);
    }

    /**
     * @notice Mark an event as refundable (cancellation).
     *         O(1) gas — fans pull their own refunds via claimRefund().
     */
    function setRefundable(bytes32 eventId) external onlyOwner {
        EventConfig storage e = events[eventId];
        if (e.kickoff == 0) revert EventNotConfigured();
        e.refundable = true;
        emit RefundableSet(eventId);
    }

    /**
     * @notice Refund a single ticket — used for postponement opt-out (100%).
     *         Called by platform within 48h opt-out window after postponement.
     */
    function refundOne(bytes32 ticketId) external onlyOwner nonReentrant {
        TicketDeposit storage t = tickets[ticketId];
        if (t.amount == 0) revert NoDepositFound();
        if (t.returned) revert TicketAlreadyReturned();
        if (t.refunded) revert TicketAlreadyRefunded();

        uint256 amount = t.amount;
        address fan    = t.fan;
        bytes32 eventId = t.eventId;

        // Reduce vendor claimable by this amount
        // (eventId not stored on ticket — amount deducted from total via accounting)
        EventConfig storage e = events[eventId];
        if (e.kickoff != 0) {
            if (e.vendorClaimable >= amount) e.vendorClaimable -= amount;
            else e.vendorClaimable = 0;
        }
        t.refunded = true;

        usdc.transfer(fan, amount);

        emit RefundedOne(ticketId, fan, amount);
    }

    // ── External — Django-initiated per-fan (Celery tasks) ────────────────────

    /**
     * @notice Fan deposits USDC for a ticket purchase.
     *         Called by Django's submit_deposit Celery task.
     *         Idempotent — keyed by ticketId, safe to retry.
     * @param eventId   bytes32 of DB event UUID
     * @param ticketId  bytes32 of DB ticket UUID
     * @param fan       Fan's smart wallet address
     * @param amount    USDC amount (gross price paid)
     */
    function deposit(
        bytes32 eventId,
        bytes32 ticketId,
        address fan,
        uint256 amount
    ) external onlyOwner nonReentrant {
        if (amount == 0) revert ZeroAmount();
        if (fan == address(0)) revert ZeroAddress();

        EventConfig storage e = events[eventId];
        if (e.kickoff == 0) revert EventNotConfigured();

        TicketDeposit storage t = tickets[ticketId];
        if (t.amount != 0) return; // idempotent — already deposited, no revert

        // Pull USDC from platform signer who holds fan's approved funds
        usdc.transferFrom(msg.sender, address(this), amount);

        t.amount = amount;
        t.fan    = fan;
        t.eventId = eventId;

        e.vendorClaimable += amount;
        e.totalDeposited  += amount;

        emit Deposited(eventId, ticketId, fan, amount);
    }

    /**
     * @notice Transfer a ticket's deposit to BuybackPool when fan requests buyback.
     *         Zeros vendor claimable for this ticket — prevents double-claim.
     *         Only callable by the BuybackPool contract.
     *         Called by Django's submit_mark_returned task which calls
     *         BuybackPool first; BuybackPool calls markReturned() here.
     * @param eventId   bytes32 of DB event UUID
     * @param ticketId  bytes32 of DB ticket UUID
     */
    function markReturned(bytes32 eventId, bytes32 ticketId)
        external
        nonReentrant
    {
        if (msg.sender != buybackPool) revert NotBuybackPool();
        if (buybackPool == address(0)) revert BuybackPoolNotSet();

        TicketDeposit storage t = tickets[ticketId];
        if (t.eventId != eventId) revert TicketEventMismatch();
        if (t.amount == 0) revert NoDepositFound();
        if (t.returned) revert TicketAlreadyReturned();
        if (t.refunded) revert TicketAlreadyRefunded();

        EventConfig storage e = events[eventId];
        if (e.kickoff == 0) revert EventNotConfigured();

        uint256 amount = t.amount;
        t.returned = true;

        // Deduct from vendor claimable — vendor cannot claim this seat
        if (e.vendorClaimable >= amount) {
            e.vendorClaimable -= amount;
        } else {
            e.vendorClaimable = 0;
        }

        // Transfer to BuybackPool
        usdc.transfer(buybackPool, amount);

        emit DepositTransferred(ticketId, amount, buybackPool);
    }

    /**
     * @notice Vendor claims net payout after T+48h.
     *         2% booking fee deducted and sent to treasury.
     *         Net = totalDeposited minus returned tickets minus fee.
     * @param eventId  bytes32 of DB event UUID
     */
    function claimPayout(bytes32 eventId)
        external
        nonReentrant
    {
        EventConfig storage e = events[eventId];
        if (e.kickoff == 0) revert KickoffNotSet();
        if (e.payoutClaimed) revert PayoutAlreadyClaimed();
        if (e.refundable) revert EventNotRefundable(); // cancelled event

        uint256 unlockAt = e.kickoff + PAYOUT_DELAY;
        if (block.timestamp < unlockAt) revert PayoutNotYetUnlocked(unlockAt);

        // Only the registered vendor can claim
        require(msg.sender == e.vendor, "PayoutVault: not vendor");

        uint256 claimable = e.vendorClaimable;
        if (claimable == 0) revert ZeroAmount();

        // Calculate and deduct 2% booking fee from vendor's net amount
        uint256 fee = (claimable * BOOKING_FEE_BPS) / BPS_DENOM;
        uint256 net = claimable - fee;

        e.payoutClaimed   = true;
        e.vendorClaimable = 0;

        if (fee > 0) usdc.transfer(treasury, fee);
        usdc.transfer(e.vendor, net);

        emit PayoutClaimed(eventId, e.vendor, net, fee);
    }

    /**
     * @notice Fan pulls own refund after event cancellation.
     *         Requires setRefundable() to have been called first.
     *         Django-initiated via submit_claim_refund Celery task.
     *         Gas sponsored by Base Paymaster — fan pays nothing.
     * @param eventId  bytes32 of DB event UUID
     * @param ticketId bytes32 of DB ticket UUID
     */
    function claimRefund(bytes32 eventId, bytes32 ticketId)
        external
        onlyOwner
        nonReentrant
    {
        EventConfig storage e = events[eventId];
        if (!e.refundable) revert EventNotRefundable();

        TicketDeposit storage t = tickets[ticketId];
        if (t.amount == 0) revert NoDepositFound();
        if (t.returned) revert TicketAlreadyReturned(); // deposit already in BuybackPool
        if (t.refunded) revert TicketAlreadyRefunded();

        uint256 amount = t.amount;
        address fan    = t.fan;

        t.refunded = true;

        usdc.transfer(fan, amount);

        emit RefundClaimed(eventId, fan, amount);
    }

    // ── Views ──────────────────────────────────────────────────────────────────

    function getEvent(bytes32 eventId)
        external
        view
        returns (EventConfig memory)
    {
        return events[eventId];
    }

    function getTicket(bytes32 ticketId)
        external
        view
        returns (TicketDeposit memory)
    {
        return tickets[ticketId];
    }

    function payoutUnlockTime(bytes32 eventId)
        external
        view
        returns (uint256)
    {
        return events[eventId].kickoff + PAYOUT_DELAY;
    }

    function renounceOwnership() external pure override {
    revert("renounceOwnership disabled");
    }

    function setTreasury(address _treasury) external onlyOwner {
        if (_treasury == address(0)) revert ZeroAddress();
        treasury = _treasury;
        emit TreasuryUpdated(_treasury);
    }

    // ── Internal ───────────────────────────────────────────────────────────────

    event TreasuryUpdated(address indexed newTreasury);
}
