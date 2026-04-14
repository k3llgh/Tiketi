// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IPayoutVault {
    function markReturned(bytes32 eventId, bytes32 ticketId) external;
    function setRefundable(bytes32 eventId) external;
    function payoutUnlockTime(bytes32 eventId) external view returns (uint256);
}
