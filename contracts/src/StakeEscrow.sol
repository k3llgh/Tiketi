// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";
import {ReentrancyGuard} from "./utils/ReentrancyGuard.sol";
import {Ownable} from "./utils/Ownable.sol";

/**
 * @title  StakeEscrow
 * @notice Holds vendor USDC stake deposits.
 *
 *  Two tiers:
 *    SMALL — $110 USDC  (110_000_000 with 6 decimals) — instant activation
 *    BIG   — $220 USDC  (220_000_000 with 6 decimals) — admin reviews within 24h
 *
 *  Lifecycle:
 *    stake()        → vendor deposits USDC, locked in escrow
 *    requestExit()  → starts 30-day timelock
 *    claimStake()   → vendor withdraws full remaining balance after timelock
 *
 *  Punitive (not confiscatory):
 *    slash()        → 15% of original stake to treasury, 85% stays locked
 *                     vendor still calls claimStake() after timelock
 *
 *  Force majeure:
 *    forceMajeure() → marks event as admin-cancelled, no slash applied
 *                     called by platform owner when cancelling due to
 *                     government ban, natural calamity, etc.
 */
contract StakeEscrow is ReentrancyGuard, Ownable {
    // ── Constants ──────────────────────────────────────────────────────────────

    uint256 public constant SMALL_STAKE = 110_000_000;   // $110 (USDC 6 decimals)
    uint256 public constant BIG_STAKE   = 220_000_000;   // $220
    uint256 public constant SLASH_BPS   = 1500;          // 15% in basis points
    uint256 public constant BPS_DENOM   = 10_000;
    uint256 public constant EXIT_DELAY  = 30 days;

    // ── Types ──────────────────────────────────────────────────────────────────

    enum Tier { NONE, SMALL, BIG }

    enum VendorStatus {
        NONE,       // never staked
        ACTIVE,     // staked, can create events
        EXITING,    // exit requested, timelock running
        EXITED,     // stake claimed, no longer active
        SUSPENDED   // slashed, still in timelock
    }

    struct VendorState {
        Tier            tier;
        VendorStatus    status;
        uint256         stakedAmount;    // original deposit
        uint256         claimableAmount; // remaining after slash(es)
        uint256         slashedAmount;   // cumulative slashed to treasury
        uint256         exitRequestedAt; // timestamp of requestExit()
    }

    // ── Storage ────────────────────────────────────────────────────────────────

    IERC20  public immutable usdc;
    address public           treasury;

    mapping(address => VendorState) public vendors;

    // ── Events ─────────────────────────────────────────────────────────────────

    event Staked(address indexed vendor, Tier tier, uint256 amount);
    event ExitRequested(address indexed vendor, uint256 unlockAt);
    event Slashed(
        address indexed vendor,
        uint256 slashAmount,
        uint256 remaining,
        string  reason
    );
    event ForceMajeure(address indexed vendor, string reason);
    event Claimed(address indexed vendor, uint256 amount);
    event TreasuryUpdated(address indexed newTreasury);

    // ── Errors ─────────────────────────────────────────────────────────────────

    error AlreadyStaked();
    error InvalidTier();
    error InsufficientAllowance();
    error NotActive();
    error NotExiting();
    error TimelockActive(uint256 unlockAt);
    error NothingToClaim();
    error ZeroAddress();

    // ── Constructor ────────────────────────────────────────────────────────────

    constructor(address _usdc, address _treasury) Ownable(msg.sender) {
        if (_usdc == address(0) || _treasury == address(0)) revert ZeroAddress();
        usdc     = IERC20(_usdc);
        treasury = _treasury;
    }

    // ── External — vendor ──────────────────────────────────────────────────────

    /**
     * @notice Vendor stakes USDC for the chosen tier.
     * @param tier  1 = SMALL ($110), 2 = BIG ($220)
     */
    function stake(Tier tier) external nonReentrant {
        VendorState storage v = vendors[msg.sender];

        if (v.status != VendorStatus.NONE && v.status != VendorStatus.EXITED) {
            revert AlreadyStaked();
        }

        uint256 amount;
        if (tier == Tier.SMALL) {
            amount = SMALL_STAKE;
        } else if (tier == Tier.BIG) {
            amount = BIG_STAKE;
        } else {
            revert InvalidTier();
        }

        if (usdc.allowance(msg.sender, address(this)) < amount) {
            revert InsufficientAllowance();
        }

        usdc.transferFrom(msg.sender, address(this), amount);

        v.tier            = tier;
        v.status          = VendorStatus.ACTIVE;
        v.stakedAmount    = amount;
        v.claimableAmount = amount;
        v.slashedAmount   = 0;
        v.exitRequestedAt = 0;

        emit Staked(msg.sender, tier, amount);
    }

    /**
     * @notice Start the 30-day exit timelock. Vendor can no longer create events.
     */
    function requestExit() external {
        VendorState storage v = vendors[msg.sender];
        if (v.status != VendorStatus.ACTIVE && v.status != VendorStatus.SUSPENDED) {
            revert NotActive();
        }

        v.status          = VendorStatus.EXITING;
        v.exitRequestedAt = block.timestamp;

        emit ExitRequested(msg.sender, block.timestamp + EXIT_DELAY);
    }

    /**
     * @notice Claim remaining stake after 30-day timelock expires.
     */
    function claimStake() external nonReentrant {
        VendorState storage v = vendors[msg.sender];
        if (v.status != VendorStatus.EXITING) revert NotExiting();

        uint256 unlockAt = v.exitRequestedAt + EXIT_DELAY;
        if (block.timestamp < unlockAt) revert TimelockActive(unlockAt);

        uint256 amount = v.claimableAmount;
        if (amount == 0) revert NothingToClaim();

        v.status          = VendorStatus.EXITED;
        v.claimableAmount = 0;

        usdc.transfer(msg.sender, amount);

        emit Claimed(msg.sender, amount);
    }

    // ── External — platform owner ──────────────────────────────────────────────

    /**
     * @notice Slash 15% of original stake to treasury as a penalty signal.
     *         Punitive, not confiscatory — 85% stays locked for vendor to claim.
     *         Called when vendor cancels an event, triggering platform rule.
     * @param vendor  Address of the vendor being penalised.
     * @param reason  Human-readable reason (emitted in event for audit).
     */
    function slash(address vendor, string calldata reason)
        external
        onlyOwner
        nonReentrant
    {
        VendorState storage v = vendors[vendor];
        if (v.status == VendorStatus.NONE || v.status == VendorStatus.EXITED) {
            revert NotActive();
        }

        uint256 slashAmount = (v.stakedAmount * SLASH_BPS) / BPS_DENOM;
        if (slashAmount > v.claimableAmount) {
            slashAmount = v.claimableAmount;
        }

        v.claimableAmount -= slashAmount;
        v.slashedAmount   += slashAmount;
        v.status           = VendorStatus.SUSPENDED;

        usdc.transfer(treasury, slashAmount);

        emit Slashed(vendor, slashAmount, v.claimableAmount, reason);
    }

    /**
     * @notice Mark a vendor event as force majeure — no slash applied.
     *         Called by admin when cancelling due to government ban,
     *         natural calamity, or other events outside vendor control.
     * @param vendor  Address of vendor.
     * @param reason  Reason string for the audit log.
     */
    function forceMajeure(address vendor, string calldata reason)
        external
        onlyOwner
    {
        VendorState storage v = vendors[vendor];
        if (v.status == VendorStatus.NONE || v.status == VendorStatus.EXITED) {
            revert NotActive();
        }

        emit ForceMajeure(vendor, reason);
    }

    /**
     * @notice Update treasury address.
     */
    function setTreasury(address _treasury) external onlyOwner {
        if (_treasury == address(0)) revert ZeroAddress();
        treasury = _treasury;
        emit TreasuryUpdated(_treasury);
    }

    // ── Views ──────────────────────────────────────────────────────────────────

    function getVendor(address vendor)
        external
        view
        returns (VendorState memory)
    {
        return vendors[vendor];
    }

    function isActive(address vendor) external view returns (bool) {
        return vendors[vendor].status == VendorStatus.ACTIVE;
    }

    function renounceOwnership() external pure override {
    revert("renounceOwnership disabled");
    }

    function unlockTimestamp(address vendor) external view returns (uint256) {
        VendorState storage v = vendors[vendor];
        if (v.exitRequestedAt == 0) return 0;
        return v.exitRequestedAt + EXIT_DELAY;
    }
}
