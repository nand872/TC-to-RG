#!/usr/bin/env python3
"""
Protocol and selector classification helpers for Ethereum mainnet.

This module is intentionally small and explicit. It provides:
- known contract labels by address
- selector-based fallbacks for common interaction types
- a single place to extend protocol coverage over time
"""

RAILGUN_ADDRESSES = {
    "0xfa7093cdd9ee6932b4eb2c9e1cde7ce00b1fa4b9": "Railgun Proxy",
    "0xc0bef2d373a1efade8b952f33c1370e486f209cc": "Railgun Smart Wallet",
}

WRAPPER_ADDRESSES = {
    "0xc02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2".lower(): "WETH",
}

DEX_ADDRESSES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router02",
    "0x11111112542d85b3ef69ae05771c2dccff4faa26": "1inch Aggregation Router V3",
}

BRIDGE_ADDRESSES = {
    # Extend as you identify bridge contracts you care about.
}

ERC20_SELECTORS = {
    "0xa9059cbb": "transfer",
    "0x23b872dd": "transferFrom",
    "0x095ea7b3": "approve",
}

DEX_SELECTORS = {
    "0x7ff36ab5": "swapExactETHForTokens",
    "0x18cbafe5": "swapExactTokensForETH",
    "0x38ed1739": "swapExactTokensForTokens",
    "0xfb3bdb41": "swapETHForExactTokens",
    "0x4a25d94a": "swapTokensForExactETH",
    "0x8803dbee": "swapTokensForExactTokens",
}

WRAP_SELECTORS = {
    "0xd0e30db0": "deposit",
    "0x2e1a7d4d": "withdraw",
}

RAILGUN_SELECTORS = {
    # Keep this small until you decide which public methods matter most.
    "0x2c2f7b4f": "shield",
}

BRIDGE_SELECTORS = {
    # Extend as needed.
}


def classify_known_address(address):
    address = (address or "").lower()
    # Address-based labels take precedence because they are the most reliable.
    # Selector-only labels are fallbacks for contracts we have not mapped yet.
    if address in RAILGUN_ADDRESSES:
        return "contract", "railgun", RAILGUN_ADDRESSES[address]
    if address in WRAPPER_ADDRESSES:
        return "contract", "wrapper", WRAPPER_ADDRESSES[address]
    if address in DEX_ADDRESSES:
        return "contract", "dex", DEX_ADDRESSES[address]
    if address in BRIDGE_ADDRESSES:
        return "contract", "bridge", BRIDGE_ADDRESSES[address]
    return None


def classify_contract(address, selector):
    # This function classifies the interaction, not just the account type. For
    # example, a generic contract address plus a swap selector becomes `dex`,
    # while a token contract selector becomes `token_contract`.
    known = classify_known_address(address)
    if known:
        return known
    if selector in RAILGUN_SELECTORS:
        return "contract", "railgun", RAILGUN_SELECTORS[selector]
    if selector in WRAP_SELECTORS:
        return "contract", "wrapper", WRAP_SELECTORS[selector]
    if selector in DEX_SELECTORS:
        return "contract", "dex", DEX_SELECTORS[selector]
    if selector in BRIDGE_SELECTORS:
        return "contract", "bridge", BRIDGE_SELECTORS[selector]
    if selector in ERC20_SELECTORS:
        return "contract", "token_contract", ERC20_SELECTORS[selector]
    return "contract", "contract", None
