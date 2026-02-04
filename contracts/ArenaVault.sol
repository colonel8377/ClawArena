// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

/**
 * @title ArenaVault
 * @notice Secure vault contract for Agent Arena poker platform on Base Chain
 * @dev Holds player deposits and allows withdrawals only with server-signed permits
 * 
 * This contract is the "Bank" for the Arena Poker game. Players deposit tokens
 * to play, and can only withdraw with a permission slip (signature) from the
 * Python Game Server.
 * 
 * Security features:
 * - Nonce-based replay attack prevention
 * - Server signature verification using ECDSA
 * - ReentrancyGuard protection
 * - Owner-controlled server signer updates
 */
contract ArenaVault is Ownable, ReentrancyGuard {
    using ECDSA for bytes32;

    // ============================================================================
    // STATE VARIABLES
    // ============================================================================

    /// @notice The ERC20 token used for deposits/withdrawals (Clanker token)
    IERC20 public immutable token;

    /// @notice Address of the Python off-chain game engine (authorized to sign withdrawals)
    address public serverSigner;

    /// @notice Whitelist of registered OpenClaw agents
    mapping(address => bool) public agentRegistry;

    /// @notice Agent's credit balance (off-chain game credits)
    mapping(address => uint256) public deposits;

    /// @notice Last airdrop claim timestamp for each agent
    mapping(address => uint256) public lastAirdrop;

    /// @notice Nonce for each agent (prevents replay attacks)
    mapping(address => uint256) public nonces;

    /// @notice Fixed airdrop amount (100 tokens with 18 decimals)
    uint256 public constant AIRDROP_AMOUNT = 100 * 10**18;

    /// @notice Airdrop cooldown period (24 hours)
    uint256 public constant AIRDROP_COOLDOWN = 24 hours;

    // ============================================================================
    // EVENTS
    // ============================================================================

    /// @notice Emitted when an agent is registered
    event AgentRegistered(address indexed agent, uint256 timestamp);

    /// @notice Emitted when an agent is unregistered
    event AgentUnregistered(address indexed agent, uint256 timestamp);

    /// @notice Emitted when tokens are deposited
    event Deposit(
        address indexed agent,
        uint256 amount,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when tokens are withdrawn
    event Withdrawal(
        address indexed agent,
        uint256 amount,
        uint256 nonce,
        uint256 newBalance,
        uint256 timestamp
    );

    /// @notice Emitted when an airdrop is claimed
    event AirdropClaimed(
        address indexed agent,
        uint256 amount,
        uint256 timestamp
    );

    /// @notice Emitted when server signer is updated
    event ServerSignerUpdated(
        address indexed oldSigner,
        address indexed newSigner,
        uint256 timestamp
    );

    // ============================================================================
    // ERRORS
    // ============================================================================

    error NotRegistered();
    error AlreadyRegistered();
    error InvalidAmount();
    error InsufficientBalance();
    error InvalidSignature();
    error InvalidNonce();
    error AirdropCooldownActive();
    error ZeroAddress();
    error TransferFailed();

    // ============================================================================
    // CONSTRUCTOR
    // ============================================================================

    /**
     * @notice Initializes the ArenaVault contract
     * @param _token Address of the ERC20 token (Clanker token)
     * @param _serverSigner Initial address of the Python backend server
     */
    constructor(IERC20 _token, address _serverSigner) {
        if (address(_token) == address(0)) revert ZeroAddress();
        if (_serverSigner == address(0)) revert ZeroAddress();
        
        token = _token;
        serverSigner = _serverSigner;
    }

    // ============================================================================
    // AGENT MANAGEMENT (OWNER ONLY)
    // ============================================================================

    /**
     * @notice Register an OpenClaw agent to the whitelist
     * @param agent Address of the agent to register
     * @dev Only owner can register agents
     */
    function registerAgent(address agent) external onlyOwner {
        if (agent == address(0)) revert ZeroAddress();
        if (agentRegistry[agent]) revert AlreadyRegistered();
        
        agentRegistry[agent] = true;
        emit AgentRegistered(agent, block.timestamp);
    }

    /**
     * @notice Unregister an agent from the whitelist
     * @param agent Address of the agent to unregister
     * @dev Only owner can unregister agents
     */
    function unregisterAgent(address agent) external onlyOwner {
        if (!agentRegistry[agent]) revert NotRegistered();
        
        agentRegistry[agent] = false;
        emit AgentUnregistered(agent, block.timestamp);
    }

    /**
     * @notice Update the server signer address
     * @param _newSigner New address for the Python backend server
     * @dev Only owner can update the server signer
     */
    function setServerSigner(address _newSigner) external onlyOwner {
        if (_newSigner == address(0)) revert ZeroAddress();
        
        address oldSigner = serverSigner;
        serverSigner = _newSigner;
        
        emit ServerSignerUpdated(oldSigner, _newSigner, block.timestamp);
    }

    // ============================================================================
    // AIRDROP FUNCTION
    // ============================================================================

    /**
     * @notice Claim daily airdrop of tokens
     * @dev Registered agents can claim once every 24 hours
     * 
     * Requirements:
     * - Caller must be registered
     * - 24 hours must have passed since last claim
     * - Contract must have sufficient token balance
     */
    function claimAirdrop() external nonReentrant {
        // Check registration
        if (!agentRegistry[msg.sender]) revert NotRegistered();
        
        // Check cooldown
        if (block.timestamp < lastAirdrop[msg.sender] + AIRDROP_COOLDOWN) {
            revert AirdropCooldownActive();
        }
        
        // Update last airdrop timestamp
        lastAirdrop[msg.sender] = block.timestamp;
        
        // Update deposits
        deposits[msg.sender] += AIRDROP_AMOUNT;
        
        // Transfer tokens from contract's treasury to agent
        bool success = token.transfer(msg.sender, AIRDROP_AMOUNT);
        if (!success) revert TransferFailed();
        
        emit AirdropClaimed(msg.sender, AIRDROP_AMOUNT, block.timestamp);
    }

    // ============================================================================
    // DEPOSIT FUNCTION
    // ============================================================================

    /**
     * @notice Deposit tokens into the vault
     * @param amount Amount of tokens to deposit
     * @dev Transfers tokens from caller to contract and updates deposits mapping
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - Caller must have approved this contract to spend tokens
     */
    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        
        // Transfer tokens from agent to contract
        bool success = token.transferFrom(msg.sender, address(this), amount);
        if (!success) revert TransferFailed();
        
        // Update deposits
        deposits[msg.sender] += amount;
        
        emit Deposit(
            msg.sender,
            amount,
            deposits[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // WITHDRAWAL FUNCTION (CRITICAL SECURITY)
    // ============================================================================

    /**
     * @notice Withdraw tokens from the vault with server-signed permission
     * @param amount Amount of tokens to withdraw
     * @param nonce Unique nonce for this withdrawal (must match current nonce)
     * @param signature Server's signature authorizing this withdrawal
     * 
     * @dev CRITICAL SECURITY FUNCTION
     * 
     * This function implements a dual-authorization withdrawal system:
     * 1. User initiates withdrawal request
     * 2. Python backend verifies game state and signs withdrawal
     * 3. User submits signed withdrawal to this function
     * 
     * Security measures:
     * - Nonce verification prevents replay attacks
     * - Signature verification ensures backend authorization
     * - ReentrancyGuard prevents reentrancy attacks
     * 
     * Requirements:
     * - Amount must be greater than 0
     * - User must have sufficient balance
     * - Nonce must match current nonce for user
     * - Signature must be valid and from serverSigner
     */
    function withdraw(
        uint256 amount,
        uint256 nonce,
        bytes memory signature
    ) external nonReentrant {
        if (amount == 0) revert InvalidAmount();
        if (deposits[msg.sender] < amount) revert InsufficientBalance();
        if (nonce != nonces[msg.sender]) revert InvalidNonce();
        
        // Reconstruct the message hash
        // This MUST match the hash created by the Python backend
        // Format: keccak256(abi.encodePacked(address, amount, nonce))
        bytes32 messageHash = keccak256(
            abi.encodePacked(msg.sender, amount, nonce)
        );
        
        // Convert to Ethereum Signed Message format
        bytes32 ethSignedMessageHash = messageHash.toEthSignedMessageHash();
        
        // Recover the signer from the signature
        address recoveredSigner = ethSignedMessageHash.recover(signature);
        
        // Verify the signature is from the authorized server signer
        if (recoveredSigner != serverSigner) revert InvalidSignature();
        
        // Increment nonce to prevent replay attacks
        nonces[msg.sender]++;
        
        // Decrease deposits
        deposits[msg.sender] -= amount;
        
        // Transfer tokens to agent
        bool success = token.transfer(msg.sender, amount);
        if (!success) revert TransferFailed();
        
        emit Withdrawal(
            msg.sender,
            amount,
            nonce,
            deposits[msg.sender],
            block.timestamp
        );
    }

    // ============================================================================
    // VIEW FUNCTIONS
    // ============================================================================

    /**
     * @notice Get the current nonce for an agent
     * @param agent Address of the agent
     * @return Current nonce value
     */
    function getNonce(address agent) external view returns (uint256) {
        return nonces[agent];
    }

    /**
     * @notice Get the deposit balance for an agent
     * @param agent Address of the agent
     * @return Current deposit balance
     */
    function getBalance(address agent) external view returns (uint256) {
        return deposits[agent];
    }

    /**
     * @notice Check if an agent is registered
     * @param agent Address of the agent
     * @return True if registered, false otherwise
     */
    function isRegistered(address agent) external view returns (bool) {
        return agentRegistry[agent];
    }

    /**
     * @notice Get time until next airdrop is available
     * @param agent Address of the agent
     * @return Seconds until next airdrop (0 if available now)
     */
    function timeUntilNextAirdrop(address agent) external view returns (uint256) {
        uint256 nextAirdrop = lastAirdrop[agent] + AIRDROP_COOLDOWN;
        if (block.timestamp >= nextAirdrop) {
            return 0;
        }
        return nextAirdrop - block.timestamp;
    }

    /**
     * @notice Get the contract's token balance
     * @return Contract's token balance
     */
    function getContractBalance() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
}
