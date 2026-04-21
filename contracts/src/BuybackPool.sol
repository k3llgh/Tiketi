// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";
import {ReentrancyGuard} from "./utils/ReentrancyGuard.sol";
import {Ownable} from "./utils/Ownable.sol";
import {IPayoutVault} from "./interfaces/IPayoutVault.sol";

/**
 * @title  BuybackPool
 * @notice Handles all buyback-related money flows.
 *
 *  Self-funding circuit (v5):
 *    1. Fan requests buyback
 *    2. Django calls requestBuyback() here:
 *       a. This contract calls PayoutVault.markReturned(eventId, ticketId)
 *       b. PayoutVault transfers the deposit to this contract via receiveDeposit()
 *       c. This contract pays 90%/80% to fan, 10%/20% to treasury
 *
 *  Resale flow:
 *    3. New buyer pays $110 via on-ramp
 *    4. Django calls depositResale(ticketId) with USDC amount
 *       → immediately splits: 40% treasury, 60% vendor
 *       → no T+48h lock on resale proceeds
 *
 *  Platform float:
 *    fundPool()  — platform can top up for edge-case timing gaps
 *
 *  The pool is primarily self-funding. fundPool() is a safety valve.
 *
 *  Buyback guard checks (80% sell-through, 15% cap, per-user limit)
 *  are enforced by Django off-chain. This contract trusts the platform
 *  signer (owner) to only call these functions after guards pass.
 */
contract BuybackPool is ReentrancyGuard, Ownable {
    // ── Constants ──────────────────────────────────────────────────────────────

    uint256 public constant SINGLE_REFUND_BPS  = 9000;  // 90% to fan
    uint256 public constant GROUP_REFUND_BPS   = 8000;  // 80% to fan
    uint256 public constant RELIST_PLATFORM_BPS = 4000; // 40% to platform
    uint256 public constant RELIST_VENDOR_BPS   = 6000; // 60% to vendor
    uint256 public constant BPS_DENOM           = 10_000;

    // ── Types ──────────────────────────────────────────────────────────────────

    enum TicketType { SINGLE, GROUP }

    struct ReturnRecord {
        uint256     depositAmount;   // amount received from PayoutVault
        address     originalFan;
        bool        refunded;
        bool        resold;
    }

    struct ResaleRecord {
        uint256 saleAmount;
        uint256 platformCut;
        uint256 vendorCut;
        address newBuyer;
        address vendor;
    }

    // ── Storage ────────────────────────────────────────────────────────────────

    IERC20       public immutable usdc;
    address      public           treasury;
    IPayoutVault public           payoutVault; // set after deploy

    mapping(bytes32 => ReturnRecord) public returns_;  // ticketId → return record
    mapping(bytes32 => ResaleRecord) public resales;   // ticketId → resale record

    // Track pool float balance for monitoring
    uint256 public poolFloat; // USDC contributed via fundPool()

    // ── Events ─────────────────────────────────────────────────────────────────

    event DepositReceived(bytes32 indexed ticketId, uint256 amount);
    event Refunded(
        bytes32 indexed ticketId,
        address indexed fan,
        uint256 refundAmount,
        uint256 retentionAmount,
        TicketType ticketType
    );
    event TicketReturned(bytes32 indexed ticketId, address indexed fan);
    event ResaleDeposited(bytes32 indexed ticketId, uint256 amount);
    event ResaleDistributed(
        bytes32 indexed ticketId,
        address indexed vendor,
        uint256 vendorCut,
        uint256 platformCut
    );
    event PoolFunded(address indexed funder, uint256 amount);
    event PayoutVaultUpdated(address indexed newVault);
    event TreasuryUpdated(address indexed newTreasury);

    // ── Errors ─────────────────────────────────────────────────────────────────

    error NotPayoutVault();
    error TicketAlreadyRegistered();
    error TicketNotFound();
    error AlreadyRefunded();
    error AlreadyResold();
    error InsufficientPoolBalance();
    error ZeroAddress();
    error ZeroAmount();
    error PayoutVaultNotSet();
    error InvalidVendor();

    // ── Constructor ────────────────────────────────────────────────────────────

    constructor(address _usdc, address _treasury) Ownable(msg.sender) {
        if (_usdc == address(0) || _treasury == address(0)) revert ZeroAddress();
        usdc     = IERC20(_usdc);
        treasury = _treasury;
    }

    // ── External — called by PayoutVault only ──────────────────────────────────

    /**
     * @notice Receive a ticket deposit transferred from PayoutVault.markReturned().
     *         Access-controlled to PayoutVault address only.
     *         The USDC transfer happens in PayoutVault before this is called —
     *         this function just registers the receipt for accounting.
     * @param ticketId  bytes32 of DB ticket UUID
     * @param amount    USDC amount received
     * @param fan       Original fan address
     */
    function receiveDeposit(bytes32 ticketId, uint256 amount, address fan)
        external
    {
        if (msg.sender != address(payoutVault)) revert NotPayoutVault();
        if (amount == 0) revert ZeroAmount();
        if (fan == address(0)) revert ZeroAddress();

        ReturnRecord storage r = returns_[ticketId];
        if (r.depositAmount != 0) revert TicketAlreadyRegistered();

        r.depositAmount = amount;
        r.originalFan   = fan;

        emit DepositReceived(ticketId, amount);
    }

    // ── External — platform owner (Django-initiated) ───────────────────────────

    /**
     * @notice Process a full buyback: record return + pay fan.
     *         Django calls this after:
     *           1. Verifying all off-chain guards (sold-out, 15% cap, 2-tx limit)
     *           2. Updating DB ticket status to 'returned'
     *         This function calls PayoutVault.markReturned() which transfers
     *         the deposit to this contract via receiveDeposit().
     *
     * @param eventId     bytes32 of DB event UUID
     * @param ticketId    bytes32 of DB ticket UUID
     * @param fan         Fan's smart wallet address
     * @param ticketType  SINGLE (90% refund) or GROUP (80% refund)
     */
    function requestBuyback(
        bytes32    eventId,
        bytes32    ticketId,
        address    fan,
        TicketType ticketType
    ) external onlyOwner nonReentrant {
        if (address(payoutVault) == address(0)) revert PayoutVaultNotSet();
        if (fan == address(0)) revert ZeroAddress();

        ReturnRecord storage r = returns_[ticketId];
        if (r.refunded) revert AlreadyRefunded();

        // Step 1: Tell PayoutVault to zero vendor claimable and transfer deposit here.
        //         PayoutVault calls receiveDeposit() which registers r.depositAmount.
        payoutVault.markReturned(eventId, ticketId);

        // After markReturned(), receiveDeposit() has been called and r.depositAmount is set.
        uint256 deposit = returns_[ticketId].depositAmount;
        if (deposit == 0) revert TicketNotFound();

        // Step 2: Calculate refund based on ticket type.
        uint256 refundBps = (ticketType == TicketType.SINGLE)
            ? SINGLE_REFUND_BPS
            : GROUP_REFUND_BPS;

        uint256 refundAmount    = (deposit * refundBps) / BPS_DENOM;
        uint256 retentionAmount = deposit - refundAmount;

        // Step 3: Mark refunded before transfers (CEI pattern).
        returns_[ticketId].refunded     = true;
        returns_[ticketId].originalFan  = fan;

        // Step 4: Transfer refund to fan, retention to treasury.
        usdc.transfer(fan, refundAmount);
        if (retentionAmount > 0) usdc.transfer(treasury, retentionAmount);

        emit TicketReturned(ticketId, fan);
        emit Refunded(ticketId, fan, refundAmount, retentionAmount, ticketType);
    }

    /**
     * @notice Accept resale payment and immediately distribute 40/60.
     *         Called by Django after on-ramp partner confirms $110 payment.
     *         No T+48h lock — resale proceeds distributed immediately.
     *         The USDC is pulled from Django's platform wallet via transferFrom.
     *
     * @param ticketId   bytes32 of DB ticket UUID
     * @param amount     USDC amount (110% of original price)
     * @param vendor     Vendor's smart wallet address (receives 60%)
     * @param newBuyer   New buyer's address (for record keeping)
     */
    function depositResale(
        bytes32 ticketId,
        uint256 amount,
        address vendor,
        address newBuyer
    ) external onlyOwner nonReentrant {
        if (amount == 0) revert ZeroAmount();
        if (vendor == address(0) || newBuyer == address(0)) revert ZeroAddress();

        ReturnRecord storage r = returns_[ticketId];
        if (r.depositAmount == 0) revert TicketNotFound(); // must have been returned first
        if (r.resold) revert AlreadyResold();

        ResaleRecord storage rs = resales[ticketId];
        if (rs.saleAmount != 0) revert AlreadyResold();

        // Pull USDC from platform wallet (on-ramp funds held there)
        usdc.transferFrom(msg.sender, address(this), amount);

        // Calculate 40/60 split
        uint256 platformCut = (amount * RELIST_PLATFORM_BPS) / BPS_DENOM;
        uint256 vendorCut   = amount - platformCut; // avoids rounding dust

        // Record before transfers (CEI)
        r.resold = true;
        rs.saleAmount  = amount;
        rs.platformCut = platformCut;
        rs.vendorCut   = vendorCut;
        rs.newBuyer    = newBuyer;
        rs.vendor      = vendor;

        // Distribute immediately — no T+48h lock on resale
        usdc.transfer(treasury, platformCut);
        usdc.transfer(vendor, vendorCut);

        emit ResaleDeposited(ticketId, amount);
        emit ResaleDistributed(ticketId, vendor, vendorCut, platformCut);
    }

    /**
     * @notice Record on-chain proof of ticket ownership transfer.
     *         Emits TicketReturned event for dispute resolution.
     *         Called by Django's activate_relist Celery task.
     *         Note: requestBuyback() already emits TicketReturned —
     *         this is for the relist activation record (all returned → relisted).
     * @param ticketId  bytes32 of DB ticket UUID
     */
    function recordReturn(bytes32 ticketId) external onlyOwner {
        ReturnRecord storage r = returns_[ticketId];
        if (r.depositAmount == 0) revert TicketNotFound();
        emit TicketReturned(ticketId, r.originalFan);
    }

    /**
     * @notice Platform tops up the USDC float buffer.
     *         Used for edge-case timing gaps between markReturned() and refund().
     *         In normal operation, the pool is self-funding from received deposits.
     */
    function fundPool(uint256 amount) external onlyOwner nonReentrant {
        if (amount == 0) revert ZeroAmount();
        usdc.transferFrom(msg.sender, address(this), amount);
        poolFloat += amount;
        emit PoolFunded(msg.sender, amount);
    }

    // ── External — admin config ────────────────────────────────────────────────

    /**
     * @notice Set PayoutVault address. Called once after PayoutVault deployed.
     */
    function setPayoutVault(address _vault) external onlyOwner {
        if (_vault == address(0)) revert ZeroAddress();
        if (address(payoutVault) != address(0)) revert PayoutVaultAlreadySet();
        payoutVault = IPayoutVault(_vault);
        emit PayoutVaultUpdated(_vault);
    }

    function setTreasury(address _treasury) external onlyOwner {
        if (_treasury == address(0)) revert ZeroAddress();
        treasury = _treasury;
        emit TreasuryUpdated(_treasury);
    }

    // ── Views ──────────────────────────────────────────────────────────────────

    function getReturn(bytes32 ticketId)
        external
        view
        returns (ReturnRecord memory)
    {
        return returns_[ticketId];
    }

    function getResale(bytes32 ticketId)
        external
        view
        returns (ResaleRecord memory)
    {
        return resales[ticketId];
    }

    function poolBalance() external view returns (uint256) {
        return usdc.balanceOf(address(this));
    }
    function renounceOwnership() external pure override {
    revert("renounceOwnership disabled");
    }
}
