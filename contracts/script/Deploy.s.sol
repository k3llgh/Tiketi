// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {StakeEscrow} from "../src/StakeEscrow.sol";
import {PayoutVault} from "../src/PayoutVault.sol";
import {BuybackPool} from "../src/BuybackPool.sol";

/**
 * @notice Deploys all three Tiketi contracts in the correct order
 *         and wires their cross-references.
 *
 *  Order matters:
 *    1. StakeEscrow   (no dependencies)
 *    2. PayoutVault   (no dependencies at construction)
 *    3. BuybackPool   (no dependencies at construction)
 *    4. Wire: vault.setBuybackPool(pool)
 *    5. Wire: pool.setPayoutVault(vault)
 *
 *  Run on Base Sepolia:
 *    forge script script/Deploy.s.sol \
 *      --rpc-url base_sepolia \
 *      --broadcast \
 *      --verify \
 *      -vvvv
 *
 *  Run on Base mainnet:
 *    forge script script/Deploy.s.sol \
 *      --rpc-url base \
 *      --broadcast \
 *      --verify \
 *      -vvvv
 */
contract Deploy is Script {
    // Base mainnet USDC address
    address constant USDC_BASE_MAINNET  = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    // Base Sepolia USDC (testnet faucet token)
    address constant USDC_BASE_SEPOLIA  = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer    = vm.addr(deployerKey);
        address treasury    = vm.envAddress("TREASURY_ADDRESS");

        // Detect network by chain ID
        bool isMainnet = block.chainid == 8453;
        address usdcAddress = isMainnet ? USDC_BASE_MAINNET : USDC_BASE_SEPOLIA;

        console2.log("=== Tiketi Contract Deployment ===");
        console2.log("Chain ID:    ", block.chainid);
        console2.log("Deployer:    ", deployer);
        console2.log("Treasury:    ", treasury);
        console2.log("USDC:        ", usdcAddress);
        console2.log("Network:     ", isMainnet ? "Base Mainnet" : "Base Sepolia");
        console2.log("");

        vm.startBroadcast(deployerKey);

        // 1. Deploy StakeEscrow
        StakeEscrow escrow = new StakeEscrow(usdcAddress, treasury);
        console2.log("StakeEscrow deployed: ", address(escrow));

        // 2. Deploy PayoutVault
        PayoutVault vault = new PayoutVault(usdcAddress, treasury);
        console2.log("PayoutVault deployed: ", address(vault));

        // 3. Deploy BuybackPool
        BuybackPool pool = new BuybackPool(usdcAddress, treasury);
        console2.log("BuybackPool deployed: ", address(pool));

        // 4. Wire cross-references
        vault.setBuybackPool(address(pool));
        pool.setPayoutVault(address(vault));
        console2.log("");
        console2.log("Cross-references wired.");

        vm.stopBroadcast();

        console2.log("");
        console2.log("=== Deployment Summary ===");
        console2.log("StakeEscrow: ", address(escrow));
        console2.log("PayoutVault: ", address(vault));
        console2.log("BuybackPool: ", address(pool));
        console2.log("");
        console2.log("Next steps:");
        console2.log("1. Copy addresses to Django contracts app settings");
        console2.log("2. Verify on Basescan (--verify flag handles this)");
        console2.log("3. Fund BuybackPool with initial float via fundPool()");
        console2.log("4. Transfer ownership to multisig if applicable");
    }
}
