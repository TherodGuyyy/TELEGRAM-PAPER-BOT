"""
Fetches live prices from DEXScreener for tokens you've paper-entered.
Same public API the memecoin bot already uses — no key needed.
"""

import logging
import requests

log = logging.getLogger("price_source")

DEXSCREENER_BASE = "https://api.dexscreener.com"


def get_current_price(token_address: str) -> float | None:
    """Returns the current USD price for a Solana token, or None if
    unavailable (e.g. no active pair, or a network hiccup)."""
    url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{token_address}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pairs = [p for p in data.get("pairs", []) if p.get("chainId") == "solana"]
        if not pairs:
            return None
        # Use the pair with the highest liquidity, same approach as the
        # memecoin bot, to avoid picking a thin/stale pair by accident.
        best_pair = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
        price = best_pair.get("priceUsd")
        return float(price) if price is not None else None
    except (requests.RequestException, ValueError, TypeError) as e:
        log.warning("Failed to fetch price for %s: %s", token_address, e)
        return None
