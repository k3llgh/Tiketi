// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {PayoutVault} from "../src/PayoutVault.sol";
import {BuybackPool} from "../src/BuybackPool.sol";
import {MockUSDC} from "./MockUSDC.sol";

contract PayoutVaultTest is Test {
    PayoutVault public vault;
    BuybackPool public pool;
    MockUSDC    public usdc;

    address public owner    = makeAddr("owner");
    address public treasury = makeAddr("treasury");
    address public vendor   = makeAddr("vendor");
    address public fan      = makeAddr("fan");
    address public fan2     = makeAddr("fan2");

    bytes32 constant EVENT_A  = keccak256("event-a");
    bytes32 constant TICKET_1 = keccak256("ticket-1");
    bytes32 constant TICKET_2 = keccak256("ticket-2");
    bytes32 constant TICKET_3 = keccak256("ticket-3");

    uint256 constant TICKET_PRICE = 100_000_000; // $100
    uint256 constant KICKOFF      = 1_800_000_000; // far future Unix timestamp

    function setUp() public {
        vm.startPrank(owner);
        usdc  = new MockUSDC();
        vault = new PayoutVault(address(usdc), treasury);
        pool  = new BuybackPool(address(usdc), treasury);

        vault.setBuybackPool(address(pool));
        pool.setPayoutVault(address(vault));

        vault.setKickoff(EVENT_A, KICKOFF, vendor);
        vm.stopPrank();

        // Fund owner (platform signer) with USDC to simulate fan payments
        usdc.mint(owner, 10_000_000_000);
        vm.prank(owner);
        usdc.approve(address(vault), type(uint256).max);
    }

    // ── setKickoff() ───────────────────────────────────────────────────────────

    function test_setKickoff_stores_config() public view {
        PayoutVault.EventConfig memory e = vault.getEvent(EVENT_A);
        assertEq(e.kickoff, KICKOFF);
        assertEq(e.vendor, vendor);
        assertFalse(e.refundable);
        assertFalse(e.payoutClaimed);
    }

    function test_setKickoff_reverts_if_already_set() public {
        vm.prank(owner);
        vm.expectRevert(PayoutVault.KickoffAlreadySet.selector);
        vault.setKickoff(EVENT_A, KICKOFF + 1, vendor);
    }

    function test_setKickoff_reverts_zero_vendor() public {
        bytes32 newEvent = keccak256("event-new");
        vm.prank(owner);
        vm.expectRevert(PayoutVault.ZeroAddress.selector);
        vault.setKickoff(newEvent, KICKOFF, address(0));
    }

    // ── deposit() ─────────────────────────────────────────────────────────────

    function test_deposit_stores_ticket() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        PayoutVault.TicketDeposit memory t = vault.getTicket(TICKET_1);
        assertEq(t.amount, TICKET_PRICE);
        assertEq(t.fan, fan);
        assertFalse(t.returned);
        assertFalse(t.refunded);
    }

    function test_deposit_increases_vendor_claimable() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        PayoutVault.EventConfig memory e = vault.getEvent(EVENT_A);
        assertEq(e.vendorClaimable, TICKET_PRICE);
        assertEq(e.totalDeposited,  TICKET_PRICE);
    }

    function test_deposit_is_idempotent() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        // Second call with same ticketId — should not revert, no double-deposit
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        PayoutVault.EventConfig memory e = vault.getEvent(EVENT_A);
        assertEq(e.vendorClaimable, TICKET_PRICE); // not doubled
    }

    function test_deposit_emits_event() public {
        vm.prank(owner);
        vm.expectEmit(true, true, false, true);
        emit PayoutVault.Deposited(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
    }

    function test_deposit_reverts_zero_amount() public {
        vm.prank(owner);
        vm.expectRevert(PayoutVault.ZeroAmount.selector);
        vault.deposit(EVENT_A, TICKET_1, fan, 0);
    }

    // ── claimPayout() ─────────────────────────────────────────────────────────

    function test_claimPayout_after_48h() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.warp(KICKOFF + 48 hours + 1);

        uint256 vendorBefore   = usdc.balanceOf(vendor);
        uint256 treasuryBefore = usdc.balanceOf(treasury);

        vm.prank(vendor);
        vault.claimPayout(EVENT_A);

        uint256 expectedFee = (TICKET_PRICE * 200) / 10_000; // 2%
        uint256 expectedNet = TICKET_PRICE - expectedFee;

        assertEq(usdc.balanceOf(vendor),   vendorBefore + expectedNet);
        assertEq(usdc.balanceOf(treasury), treasuryBefore + expectedFee);
    }

    function test_claimPayout_reverts_before_48h() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.warp(KICKOFF + 47 hours);
        vm.prank(vendor);
        vm.expectRevert(
            abi.encodeWithSelector(
                PayoutVault.PayoutNotYetUnlocked.selector,
                KICKOFF + 48 hours
            )
        );
        vault.claimPayout(EVENT_A);
    }

    function test_claimPayout_reverts_double_claim() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vault.claimPayout(EVENT_A);

        vm.prank(vendor);
        vm.expectRevert(PayoutVault.PayoutAlreadyClaimed.selector);
        vault.claimPayout(EVENT_A);
    }

    function test_claimPayout_reverts_if_refundable() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vm.expectRevert(PayoutVault.EventNotRefundable.selector);
        vault.claimPayout(EVENT_A);
    }

    function test_claimPayout_emits_event() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        vm.warp(KICKOFF + 48 hours + 1);

        uint256 expectedFee = (TICKET_PRICE * 200) / 10_000;
        uint256 expectedNet = TICKET_PRICE - expectedFee;

        vm.prank(vendor);
        vm.expectEmit(true, false, false, true);
        emit PayoutVault.PayoutClaimed(EVENT_A, vendor, expectedNet, expectedFee);
        vault.claimPayout(EVENT_A);
    }

    // ── markReturned() + buyback circuit ──────────────────────────────────────

    function test_markReturned_zeroes_vendor_claimable() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        // Simulate BuybackPool calling markReturned
        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        PayoutVault.EventConfig memory e = vault.getEvent(EVENT_A);
        assertEq(e.vendorClaimable, 0);

        PayoutVault.TicketDeposit memory t = vault.getTicket(TICKET_1);
        assertTrue(t.returned);
    }

    function test_markReturned_transfers_to_buyback_pool() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        uint256 poolBefore = usdc.balanceOf(address(pool));

        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        assertEq(usdc.balanceOf(address(pool)), poolBefore + TICKET_PRICE);
    }

    function test_markReturned_reverts_if_not_pool() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vm.expectRevert(PayoutVault.NotBuybackPool.selector);
        vault.markReturned(EVENT_A, TICKET_1);
    }

    function test_markReturned_reverts_double_return() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        vm.prank(address(pool));
        vm.expectRevert(PayoutVault.TicketAlreadyReturned.selector);
        vault.markReturned(EVENT_A, TICKET_1);
    }

    function test_partial_buyback_reduces_claimable_correctly() public {
        // Two tickets purchased
        vm.startPrank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan,  TICKET_PRICE);
        vault.deposit(EVENT_A, TICKET_2, fan2, TICKET_PRICE);
        vm.stopPrank();

        assertEq(vault.getEvent(EVENT_A).vendorClaimable, TICKET_PRICE * 2);

        // One ticket returned
        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        // Vendor claimable reduced by one ticket only
        assertEq(vault.getEvent(EVENT_A).vendorClaimable, TICKET_PRICE);

        // Vendor claims remaining after 48h
        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vault.claimPayout(EVENT_A);

        uint256 expectedFee = (TICKET_PRICE * 200) / 10_000;
        assertEq(usdc.balanceOf(vendor), TICKET_PRICE - expectedFee);
    }

    // ── setRefundable() + claimRefund() ───────────────────────────────────────

    function test_setRefundable_enables_fan_claims() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        assertTrue(vault.getEvent(EVENT_A).refundable);
    }

    function test_claimRefund_returns_full_amount() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        uint256 fanBefore = usdc.balanceOf(fan);

        vm.prank(owner); // Django-initiated
        vault.claimRefund(EVENT_A, TICKET_1);

        assertEq(usdc.balanceOf(fan), fanBefore + TICKET_PRICE);
    }

    function test_claimRefund_emits_event() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        vm.prank(owner);
        vm.expectEmit(true, true, false, true);
        emit PayoutVault.RefundClaimed(EVENT_A, fan, TICKET_PRICE);
        vault.claimRefund(EVENT_A, TICKET_1);
    }

    function test_claimRefund_reverts_if_not_refundable() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vm.expectRevert(PayoutVault.EventNotRefundable.selector);
        vault.claimRefund(EVENT_A, TICKET_1);
    }

    function test_claimRefund_reverts_double_claim() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        vm.prank(owner);
        vault.setRefundable(EVENT_A);
        vm.prank(owner);
        vault.claimRefund(EVENT_A, TICKET_1);

        vm.prank(owner);
        vm.expectRevert(PayoutVault.TicketAlreadyRefunded.selector);
        vault.claimRefund(EVENT_A, TICKET_1);
    }

    function test_claimRefund_skips_returned_tickets() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        // Ticket returned via buyback
        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        // Cannot claim refund on already-returned ticket
        vm.prank(owner);
        vm.expectRevert(PayoutVault.TicketAlreadyReturned.selector);
        vault.claimRefund(EVENT_A, TICKET_1);
    }

    // ── refundOne() ───────────────────────────────────────────────────────────

    function test_refundOne_postpone_opt_out() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);

        uint256 fanBefore = usdc.balanceOf(fan);

        vm.prank(owner);
        vault.refundOne(TICKET_1);

        assertEq(usdc.balanceOf(fan), fanBefore + TICKET_PRICE);

        PayoutVault.TicketDeposit memory t = vault.getTicket(TICKET_1);
        assertTrue(t.refunded);
    }

    function test_refundOne_reverts_if_already_returned() public {
        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, TICKET_PRICE);
        vm.prank(address(pool));
        vault.markReturned(EVENT_A, TICKET_1);

        vm.prank(owner);
        vm.expectRevert(PayoutVault.TicketAlreadyReturned.selector);
        vault.refundOne(TICKET_1);
    }

    // ── payoutUnlockTime() ────────────────────────────────────────────────────

    function test_payoutUnlockTime_correct() public view {
        assertEq(vault.payoutUnlockTime(EVENT_A), KICKOFF + 48 hours);
    }

    // ── Fuzz ──────────────────────────────────────────────────────────────────

    function testFuzz_deposit_and_claim(uint256 price) public {
        price = bound(price, 1_000_000, 1_000_000_000); // $1 to $1000

        // Ensure owner has enough USDC
        usdc.mint(owner, price);
        vm.prank(owner);
        usdc.approve(address(vault), price);

        vm.prank(owner);
        vault.deposit(EVENT_A, TICKET_1, fan, price);

        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vault.claimPayout(EVENT_A);

        uint256 expectedFee = (price * 200) / 10_000;
        uint256 expectedNet = price - expectedFee;

        assertEq(usdc.balanceOf(vendor),   expectedNet);
        assertEq(usdc.balanceOf(treasury), expectedFee);
    }
}
