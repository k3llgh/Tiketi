// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {BuybackPool} from "../src/BuybackPool.sol";
import {PayoutVault} from "../src/PayoutVault.sol";
import {MockUSDC} from "./MockUSDC.sol";

contract BuybackPoolTest is Test {
    BuybackPool public pool;
    PayoutVault public vault;
    MockUSDC    public usdc;

    address public owner    = makeAddr("owner");
    address public treasury = makeAddr("treasury");
    address public vendor   = makeAddr("vendor");
    address public fan      = makeAddr("fan");
    address public newBuyer = makeAddr("newBuyer");
    address public stranger = makeAddr("stranger");

    bytes32 constant EVENT_A  = keccak256("event-a");
    bytes32 constant TICKET_1 = keccak256("ticket-1");
    bytes32 constant TICKET_2 = keccak256("ticket-2");

    uint256 constant TICKET_PRICE  = 100_000_000;  // $100
    uint256 constant RELIST_PRICE  = 110_000_000;  // $110 (110%)
    uint256 constant KICKOFF       = 1_800_000_000;

    function setUp() public {
        vm.startPrank(owner);
        usdc  = new MockUSDC();
        vault = new PayoutVault(address(usdc), treasury);
        pool  = new BuybackPool(address(usdc), treasury);

        vault.setBuybackPool(address(pool));
        pool.setPayoutVault(address(vault));

        vault.setKickoff(EVENT_A, KICKOFF, vendor);
        vm.stopPrank();

        // Mint USDC to owner (platform signer)
        usdc.mint(owner, 100_000_000_000);
        vm.prank(owner);
        usdc.approve(address(vault), type(uint256).max);
        vm.prank(owner);
        usdc.approve(address(pool), type(uint256).max);
    }

    // ── Helper: simulate full purchase + buyback circuit ──────────────────────

    function _purchase(bytes32 ticketId, address _fan, uint256 price) internal {
        vm.prank(owner);
        vault.deposit(EVENT_A, ticketId, _fan, price);
    }

    function _buyback(bytes32 ticketId, address _fan, BuybackPool.TicketType t)
        internal
    {
        vm.prank(owner);
        pool.requestBuyback(EVENT_A, ticketId, _fan, t);
    }

    // ── receiveDeposit() ──────────────────────────────────────────────────────

    function test_receiveDeposit_only_callable_by_vault() public {
        vm.prank(stranger);
        vm.expectRevert(BuybackPool.NotPayoutVault.selector);
        pool.receiveDeposit(TICKET_1, TICKET_PRICE, fan);
    }

    function test_receiveDeposit_reverts_zero_amount() public {
        vm.prank(address(vault));
        vm.expectRevert(BuybackPool.ZeroAmount.selector);
        pool.receiveDeposit(TICKET_1, 0, fan);
    }

    function test_receiveDeposit_reverts_zero_fan() public {
        vm.prank(address(vault));
        vm.expectRevert(BuybackPool.ZeroAddress.selector);
        pool.receiveDeposit(TICKET_1, TICKET_PRICE, address(0));
    }

    function test_receiveDeposit_reverts_if_already_registered() public {
        // First registration
        vm.prank(address(vault));
        pool.receiveDeposit(TICKET_1, TICKET_PRICE, fan);

        // Second registration with same ticketId
        vm.prank(address(vault));
        vm.expectRevert(BuybackPool.TicketAlreadyRegistered.selector);
        pool.receiveDeposit(TICKET_1, TICKET_PRICE, fan);
    }

    // ── Full buyback circuit — single ticket ──────────────────────────────────

    function test_full_circuit_single_ticket_90_percent_refund() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);

        uint256 fanBefore      = usdc.balanceOf(fan);
        uint256 treasuryBefore = usdc.balanceOf(treasury);
        uint256 vaultBefore    = usdc.balanceOf(address(vault));

        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        uint256 expectedRefund    = (TICKET_PRICE * 9000) / 10_000; // $90
        uint256 expectedRetention = TICKET_PRICE - expectedRefund;   // $10

        assertEq(usdc.balanceOf(fan),          fanBefore + expectedRefund);
        assertEq(usdc.balanceOf(treasury),     treasuryBefore + expectedRetention);
        assertEq(usdc.balanceOf(address(vault)), vaultBefore - TICKET_PRICE);
        assertEq(usdc.balanceOf(address(pool)), 0); // all distributed

        BuybackPool.ReturnRecord memory r = pool.getReturn(TICKET_1);
        assertTrue(r.refunded);
        assertEq(r.depositAmount, TICKET_PRICE);
    }

    function test_full_circuit_group_ticket_80_percent_refund() public {
        uint256 groupPrice = 300_000_000; // $300 (3 tickets at $100)
        _purchase(TICKET_1, fan, groupPrice);

        uint256 fanBefore      = usdc.balanceOf(fan);
        uint256 treasuryBefore = usdc.balanceOf(treasury);

        _buyback(TICKET_1, fan, BuybackPool.TicketType.GROUP);

        uint256 expectedRefund    = (groupPrice * 8000) / 10_000; // $240
        uint256 expectedRetention = groupPrice - expectedRefund;   // $60

        assertEq(usdc.balanceOf(fan),      fanBefore + expectedRefund);
        assertEq(usdc.balanceOf(treasury), treasuryBefore + expectedRetention);
    }

    function test_buyback_zeroes_vendor_claimable_in_vault() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        assertEq(vault.getEvent(EVENT_A).vendorClaimable, TICKET_PRICE);

        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        assertEq(vault.getEvent(EVENT_A).vendorClaimable, 0);
    }

    function test_vendor_cannot_double_claim_after_buyback() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vm.expectRevert(PayoutVault.ZeroAmount.selector);
        vault.claimPayout(EVENT_A);
    }

    function test_buyback_emits_events() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);

        uint256 expectedRefund    = (TICKET_PRICE * 9000) / 10_000;
        uint256 expectedRetention = TICKET_PRICE - expectedRefund;

        vm.prank(owner);
        vm.expectEmit(true, true, false, true);
        emit BuybackPool.Refunded(
            TICKET_1, fan, expectedRefund, expectedRetention,
            BuybackPool.TicketType.SINGLE
        );
        pool.requestBuyback(EVENT_A, TICKET_1, fan, BuybackPool.TicketType.SINGLE);
    }

    function test_buyback_reverts_double_buyback() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        vm.prank(owner);
        vm.expectRevert(BuybackPool.AlreadyRefunded.selector);
        pool.requestBuyback(EVENT_A, TICKET_1, fan, BuybackPool.TicketType.SINGLE);
    }

    // ── depositResale() — resale circuit ──────────────────────────────────────

    function test_depositResale_distributes_40_60_immediately() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        uint256 treasuryBefore = usdc.balanceOf(treasury);
        uint256 vendorBefore   = usdc.balanceOf(vendor);

        vm.prank(owner);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);

        uint256 expectedPlatform = (RELIST_PRICE * 4000) / 10_000; // $44
        uint256 expectedVendor   = RELIST_PRICE - expectedPlatform; // $66

        assertEq(usdc.balanceOf(treasury), treasuryBefore + expectedPlatform);
        assertEq(usdc.balanceOf(vendor),   vendorBefore + expectedVendor);
    }

    function test_depositResale_no_t48h_lock() public {
        // Resale proceeds distributed immediately — no kickoff + 48h required
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        // Before kickoff — resale should still work
        vm.warp(KICKOFF - 1 days);

        uint256 vendorBefore = usdc.balanceOf(vendor);
        vm.prank(owner);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);

        // Vendor received funds immediately
        assertGt(usdc.balanceOf(vendor), vendorBefore);
    }

    function test_depositResale_emits_events() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        uint256 expectedPlatform = (RELIST_PRICE * 4000) / 10_000;
        uint256 expectedVendor   = RELIST_PRICE - expectedPlatform;

        vm.prank(owner);
        vm.expectEmit(true, true, false, true);
        emit BuybackPool.ResaleDistributed(TICKET_1, vendor, expectedVendor, expectedPlatform);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);
    }

    function test_depositResale_reverts_if_not_returned_first() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);

        vm.prank(owner);
        vm.expectRevert(BuybackPool.TicketNotFound.selector);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);
    }

    function test_depositResale_reverts_double_resale() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        vm.prank(owner);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);

        vm.prank(owner);
        vm.expectRevert(BuybackPool.AlreadyResold.selector);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);
    }

    function test_depositResale_reverts_zero_vendor() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        vm.prank(owner);
        vm.expectRevert(BuybackPool.ZeroAddress.selector);
        pool.depositResale(TICKET_1, RELIST_PRICE, address(0), newBuyer);
    }

    // ── fundPool() ────────────────────────────────────────────────────────────

    function test_fundPool_increases_balance() public {
        uint256 amount = 500_000_000;
        uint256 before = usdc.balanceOf(address(pool));

        vm.prank(owner);
        pool.fundPool(amount);

        assertEq(usdc.balanceOf(address(pool)), before + amount);
        assertEq(pool.poolFloat(), amount);
    }

    function test_fundPool_emits_event() public {
        vm.prank(owner);
        vm.expectEmit(true, false, false, true);
        emit BuybackPool.PoolFunded(owner, 500_000_000);
        pool.fundPool(500_000_000);
    }

    function test_fundPool_reverts_zero() public {
        vm.prank(owner);
        vm.expectRevert(BuybackPool.ZeroAmount.selector);
        pool.fundPool(0);
    }

    // ── recordReturn() ────────────────────────────────────────────────────────

    function test_recordReturn_emits_ticket_returned() public {
        _purchase(TICKET_1, fan, TICKET_PRICE);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        vm.prank(owner);
        vm.expectEmit(true, true, false, false);
        emit BuybackPool.TicketReturned(TICKET_1, fan);
        pool.recordReturn(TICKET_1);
    }

    function test_recordReturn_reverts_if_not_registered() public {
        vm.prank(owner);
        vm.expectRevert(BuybackPool.TicketNotFound.selector);
        pool.recordReturn(keccak256("nonexistent"));
    }

    // ── Complete money circuit verification ───────────────────────────────────

    function test_complete_scenario_b_money_circuit() public {
        // Scenario B from spec:
        // Fan pays $100 → buyback → fan gets $90 → resale at $110 → 40/60 split
        // Platform net: −$90 refund + $10 retention + $44 relist = −$36
        // Vendor net: $66 (relist only, PayoutVault claim = $0)

        uint256 platformStart  = usdc.balanceOf(treasury);
        uint256 vendorStart    = usdc.balanceOf(vendor);
        uint256 fanStart       = usdc.balanceOf(fan);

        // 1. Purchase
        _purchase(TICKET_1, fan, TICKET_PRICE);

        // 2. Buyback
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        // 3. Resale
        vm.prank(owner);
        pool.depositResale(TICKET_1, RELIST_PRICE, vendor, newBuyer);

        // Verify fan received 90%
        assertEq(usdc.balanceOf(fan), fanStart - TICKET_PRICE + (TICKET_PRICE * 9000 / 10_000));

        // Verify vendor net = 60% of relist = $66
        uint256 vendorNet = (RELIST_PRICE * 6000) / 10_000;
        assertEq(usdc.balanceOf(vendor), vendorStart + vendorNet);

        // Verify treasury net = $10 retention + $44 relist = $54
        uint256 retention   = TICKET_PRICE - (TICKET_PRICE * 9000 / 10_000); // $10
        uint256 relist_take = (RELIST_PRICE * 4000) / 10_000;                // $44
        assertEq(usdc.balanceOf(treasury), platformStart + retention + relist_take);

        // Vendor cannot double-claim from PayoutVault
        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vm.expectRevert(PayoutVault.ZeroAmount.selector);
        vault.claimPayout(EVENT_A);
    }

    function test_complete_scenario_a_no_buyback() public {
        // Scenario A: normal sale, no buyback
        // Vendor net = $98 (after 2% fee). Platform = $2.

        uint256 vendorStart   = usdc.balanceOf(vendor);
        uint256 treasuryStart = usdc.balanceOf(treasury);

        _purchase(TICKET_1, fan, TICKET_PRICE);

        vm.warp(KICKOFF + 48 hours + 1);
        vm.prank(vendor);
        vault.claimPayout(EVENT_A);

        uint256 expectedFee = (TICKET_PRICE * 200) / 10_000; // $2
        uint256 expectedNet = TICKET_PRICE - expectedFee;     // $98

        assertEq(usdc.balanceOf(vendor),   vendorStart + expectedNet);
        assertEq(usdc.balanceOf(treasury), treasuryStart + expectedFee);
    }

    function test_scenario_d_cancellation_pull_refund() public {
        // Scenario D: cancellation → setRefundable → fans claim individually
        _purchase(TICKET_1, fan,  TICKET_PRICE);
        _purchase(TICKET_2, fan2, TICKET_PRICE);

        // Platform cancels
        vm.prank(owner);
        vault.setRefundable(EVENT_A);

        uint256 fan1Before = usdc.balanceOf(fan);
        uint256 fan2Before = usdc.balanceOf(fan2);

        // Django submits claim for each fan separately
        vm.prank(owner);
        vault.claimRefund(EVENT_A, TICKET_1);
        vm.prank(owner);
        vault.claimRefund(EVENT_A, TICKET_2);

        assertEq(usdc.balanceOf(fan),  fan1Before + TICKET_PRICE);
        assertEq(usdc.balanceOf(fan2), fan2Before + TICKET_PRICE);
    }

    // ── setPayoutVault / setTreasury ──────────────────────────────────────────

    function test_setPayoutVault_reverts_zero() public {
        vm.prank(owner);
        vm.expectRevert(BuybackPool.ZeroAddress.selector);
        pool.setPayoutVault(address(0));
    }

    function test_setTreasury_updates() public {
        address newT = makeAddr("newTreasury");
        vm.prank(owner);
        pool.setTreasury(newT);
        assertEq(pool.treasury(), newT);
    }

    // ── Fuzz ──────────────────────────────────────────────────────────────────

    function testFuzz_single_refund_always_90_percent(uint256 price) public {
        price = bound(price, 1_000_000, 1_000_000_000);
        usdc.mint(owner, price);
        vm.prank(owner);
        usdc.approve(address(vault), price);

        _purchase(TICKET_1, fan, price);

        uint256 fanBefore = usdc.balanceOf(fan);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        uint256 expected = (price * 9000) / 10_000;
        assertEq(usdc.balanceOf(fan), fanBefore + expected);
    }

    function testFuzz_group_refund_always_80_percent(uint256 price) public {
        price = bound(price, 1_000_000, 1_000_000_000);
        usdc.mint(owner, price);
        vm.prank(owner);
        usdc.approve(address(vault), price);

        _purchase(TICKET_1, fan, price);

        uint256 fanBefore = usdc.balanceOf(fan);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.GROUP);

        uint256 expected = (price * 8000) / 10_000;
        assertEq(usdc.balanceOf(fan), fanBefore + expected);
    }

    function testFuzz_relist_split_always_40_60(uint256 price) public {
        price = bound(price, 1_000_000, 1_000_000_000);
        usdc.mint(owner, price);
        vm.prank(owner);
        usdc.approve(address(vault), type(uint256).max);

        uint256 purchasePrice = (price * 10) / 11; // so relist = price
        if (purchasePrice == 0) return;

        usdc.mint(owner, purchasePrice);
        vm.prank(owner);
        usdc.approve(address(vault), purchasePrice);

        _purchase(TICKET_1, fan, purchasePrice);
        _buyback(TICKET_1, fan, BuybackPool.TicketType.SINGLE);

        uint256 vendorBefore   = usdc.balanceOf(vendor);
        uint256 treasuryBefore = usdc.balanceOf(treasury);

        vm.prank(owner);
        usdc.approve(address(pool), price);
        vm.prank(owner);
        pool.depositResale(TICKET_1, price, vendor, newBuyer);

        uint256 platformCut = (price * 4000) / 10_000;
        uint256 vendorCut   = price - platformCut;

        assertEq(usdc.balanceOf(vendor),   vendorBefore + vendorCut);
        assertEq(usdc.balanceOf(treasury), treasuryBefore + platformCut);
    }
}
