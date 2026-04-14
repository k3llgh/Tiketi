// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {StakeEscrow} from "../src/StakeEscrow.sol";
import {MockUSDC} from "./MockUSDC.sol";

contract StakeEscrowTest is Test {
    StakeEscrow public escrow;
    MockUSDC    public usdc;

    address public owner    = makeAddr("owner");
    address public treasury = makeAddr("treasury");
    address public vendor   = makeAddr("vendor");
    address public vendorB  = makeAddr("vendorB");

    uint256 constant SMALL = 110_000_000; // $110
    uint256 constant BIG   = 220_000_000; // $220

    function setUp() public {
        vm.startPrank(owner);
        usdc   = new MockUSDC();
        escrow = new StakeEscrow(address(usdc), treasury);
        vm.stopPrank();

        // Fund vendors
        usdc.mint(vendor,  500_000_000);
        usdc.mint(vendorB, 500_000_000);
    }

    // ── Helpers ────────────────────────────────────────────────────────────────

    function _stakeSmall(address v) internal {
        vm.startPrank(v);
        usdc.approve(address(escrow), SMALL);
        escrow.stake(StakeEscrow.Tier.SMALL);
        vm.stopPrank();
    }

    function _stakeBig(address v) internal {
        vm.startPrank(v);
        usdc.approve(address(escrow), BIG);
        escrow.stake(StakeEscrow.Tier.BIG);
        vm.stopPrank();
    }

    // ── stake() ────────────────────────────────────────────────────────────────

    function test_stake_small() public {
        uint256 balBefore = usdc.balanceOf(vendor);
        _stakeSmall(vendor);

        assertEq(usdc.balanceOf(vendor), balBefore - SMALL);
        assertEq(usdc.balanceOf(address(escrow)), SMALL);

        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        assertEq(uint8(v.tier),            uint8(StakeEscrow.Tier.SMALL));
        assertEq(uint8(v.status),          uint8(StakeEscrow.VendorStatus.ACTIVE));
        assertEq(v.stakedAmount,           SMALL);
        assertEq(v.claimableAmount,        SMALL);
        assertEq(v.slashedAmount,          0);
    }

    function test_stake_big() public {
        _stakeBig(vendor);
        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        assertEq(uint8(v.tier),   uint8(StakeEscrow.Tier.BIG));
        assertEq(v.stakedAmount,  BIG);
    }

    function test_stake_emits_event() public {
        vm.startPrank(vendor);
        usdc.approve(address(escrow), SMALL);
        vm.expectEmit(true, false, false, true);
        emit StakeEscrow.Staked(vendor, StakeEscrow.Tier.SMALL, SMALL);
        escrow.stake(StakeEscrow.Tier.SMALL);
        vm.stopPrank();
    }

    function test_stake_reverts_if_already_staked() public {
        _stakeSmall(vendor);
        vm.startPrank(vendor);
        usdc.approve(address(escrow), SMALL);
        vm.expectRevert(StakeEscrow.AlreadyStaked.selector);
        escrow.stake(StakeEscrow.Tier.SMALL);
        vm.stopPrank();
    }

    function test_stake_reverts_invalid_tier() public {
        vm.startPrank(vendor);
        usdc.approve(address(escrow), SMALL);
        vm.expectRevert(StakeEscrow.InvalidTier.selector);
        escrow.stake(StakeEscrow.Tier.NONE);
        vm.stopPrank();
    }

    function test_stake_reverts_insufficient_allowance() public {
        vm.startPrank(vendor);
        // No approve
        vm.expectRevert(StakeEscrow.InsufficientAllowance.selector);
        escrow.stake(StakeEscrow.Tier.SMALL);
        vm.stopPrank();
    }

    function test_isActive_returns_true_after_stake() public {
        _stakeSmall(vendor);
        assertTrue(escrow.isActive(vendor));
    }

    function test_isActive_returns_false_before_stake() public view {
        assertFalse(escrow.isActive(vendor));
    }

    // ── requestExit() ──────────────────────────────────────────────────────────

    function test_requestExit_sets_exiting_status() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();

        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        assertEq(uint8(v.status), uint8(StakeEscrow.VendorStatus.EXITING));
        assertEq(v.exitRequestedAt, block.timestamp);
    }

    function test_requestExit_emits_event() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        vm.expectEmit(true, false, false, true);
        emit StakeEscrow.ExitRequested(vendor, block.timestamp + 30 days);
        escrow.requestExit();
    }

    function test_requestExit_reverts_if_not_active() public {
        vm.prank(vendor);
        vm.expectRevert(StakeEscrow.NotActive.selector);
        escrow.requestExit();
    }

    function test_unlockTimestamp_correct() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();
        assertEq(escrow.unlockTimestamp(vendor), block.timestamp + 30 days);
    }

    // ── claimStake() ───────────────────────────────────────────────────────────

    function test_claimStake_after_30_days() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();

        vm.warp(block.timestamp + 30 days + 1);

        uint256 balBefore = usdc.balanceOf(vendor);
        vm.prank(vendor);
        escrow.claimStake();

        assertEq(usdc.balanceOf(vendor), balBefore + SMALL);
        assertEq(usdc.balanceOf(address(escrow)), 0);

        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        assertEq(uint8(v.status),    uint8(StakeEscrow.VendorStatus.EXITED));
        assertEq(v.claimableAmount,  0);
    }

    function test_claimStake_emits_event() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();
        vm.warp(block.timestamp + 30 days + 1);

        vm.prank(vendor);
        vm.expectEmit(true, false, false, true);
        emit StakeEscrow.Claimed(vendor, SMALL);
        escrow.claimStake();
    }

    function test_claimStake_reverts_before_timelock() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();

        vm.warp(block.timestamp + 29 days);
        vm.prank(vendor);
        vm.expectRevert(
            abi.encodeWithSelector(
                StakeEscrow.TimelockActive.selector,
                block.timestamp + 1 days + 1
            )
        );
        escrow.claimStake();
    }

    function test_claimStake_reverts_if_not_exiting() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        vm.expectRevert(StakeEscrow.NotExiting.selector);
        escrow.claimStake();
    }

    // ── slash() ────────────────────────────────────────────────────────────────

    function test_slash_sends_15_percent_to_treasury() public {
        _stakeSmall(vendor);

        uint256 treasuryBefore = usdc.balanceOf(treasury);

        vm.prank(owner);
        escrow.slash(vendor, "Vendor cancelled event");

        uint256 expectedSlash = (SMALL * 1500) / 10_000; // 15%
        assertEq(usdc.balanceOf(treasury), treasuryBefore + expectedSlash);

        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        assertEq(v.claimableAmount, SMALL - expectedSlash);
        assertEq(v.slashedAmount,   expectedSlash);
        assertEq(uint8(v.status),   uint8(StakeEscrow.VendorStatus.SUSPENDED));
    }

    function test_slash_85_percent_stays_claimable() public {
        _stakeSmall(vendor);
        vm.prank(owner);
        escrow.slash(vendor, "test");

        StakeEscrow.VendorState memory v = escrow.getVendor(vendor);
        uint256 expectedRemaining = SMALL - (SMALL * 1500) / 10_000;
        assertEq(v.claimableAmount, expectedRemaining);
    }

    function test_slash_emits_event() public {
        _stakeSmall(vendor);
        uint256 expectedSlash = (SMALL * 1500) / 10_000;

        vm.prank(owner);
        vm.expectEmit(true, false, false, true);
        emit StakeEscrow.Slashed(vendor, expectedSlash, SMALL - expectedSlash, "test reason");
        escrow.slash(vendor, "test reason");
    }

    function test_slash_then_claim_after_timelock() public {
        _stakeSmall(vendor);

        vm.prank(owner);
        escrow.slash(vendor, "bad vendor");

        vm.prank(vendor);
        escrow.requestExit();

        vm.warp(block.timestamp + 30 days + 1);

        uint256 expectedRemaining = SMALL - (SMALL * 1500) / 10_000;
        uint256 balBefore         = usdc.balanceOf(vendor);

        vm.prank(vendor);
        escrow.claimStake();

        assertEq(usdc.balanceOf(vendor), balBefore + expectedRemaining);
    }

    function test_slash_reverts_if_not_owner() public {
        _stakeSmall(vendor);
        vm.prank(vendorB);
        vm.expectRevert();
        escrow.slash(vendor, "unauthorized");
    }

    function test_slash_reverts_if_not_staked() public {
        vm.prank(owner);
        vm.expectRevert(StakeEscrow.NotActive.selector);
        escrow.slash(vendor, "not staked");
    }

    // ── forceMajeure() ─────────────────────────────────────────────────────────

    function test_forceMajeure_emits_event_no_slash() public {
        _stakeSmall(vendor);

        uint256 treasuryBefore  = usdc.balanceOf(treasury);
        uint256 claimableBefore = escrow.getVendor(vendor).claimableAmount;

        vm.prank(owner);
        vm.expectEmit(true, false, false, true);
        emit StakeEscrow.ForceMajeure(vendor, "stadium flooded");
        escrow.forceMajeure(vendor, "stadium flooded");

        // No slash occurred
        assertEq(usdc.balanceOf(treasury), treasuryBefore);
        assertEq(escrow.getVendor(vendor).claimableAmount, claimableBefore);
    }

    function test_forceMajeure_reverts_if_not_owner() public {
        _stakeSmall(vendor);
        vm.prank(vendorB);
        vm.expectRevert();
        escrow.forceMajeure(vendor, "unauthorized");
    }

    // ── restake after exit ─────────────────────────────────────────────────────

    function test_can_restake_after_exit() public {
        _stakeSmall(vendor);
        vm.prank(vendor);
        escrow.requestExit();
        vm.warp(block.timestamp + 30 days + 1);
        vm.prank(vendor);
        escrow.claimStake();

        // Vendor can stake again
        _stakeBig(vendor);
        assertTrue(escrow.isActive(vendor));
    }

    // ── setTreasury ────────────────────────────────────────────────────────────

    function test_setTreasury_updates_address() public {
        address newTreasury = makeAddr("newTreasury");
        vm.prank(owner);
        escrow.setTreasury(newTreasury);
        assertEq(escrow.treasury(), newTreasury);
    }

    function test_setTreasury_reverts_zero_address() public {
        vm.prank(owner);
        vm.expectRevert(StakeEscrow.ZeroAddress.selector);
        escrow.setTreasury(address(0));
    }

    // ── Fuzz ───────────────────────────────────────────────────────────────────

    function testFuzz_slash_never_exceeds_claimable(uint256 extraFunding) public {
        extraFunding = bound(extraFunding, 0, 1_000_000_000);
        _stakeSmall(vendor);

        // Slash once
        vm.prank(owner);
        escrow.slash(vendor, "first slash");

        uint256 claimable = escrow.getVendor(vendor).claimableAmount;
        assertLe(claimable, SMALL);
        assertGe(claimable, 0);
    }
}
