POSITIVE_KEYWORDS = {
    "etf approval": 1.0,
    "approves": 0.7,
    "rally": 0.6,
    "surge": 0.6,
    "adoption": 0.6,
    "bullish": 0.7,
    "inflow": 0.5,
    "inflows": 0.5,
    "all-time high": 0.9,
    "breaks above": 0.5,
    "buys": 0.3,
    "partnership": 0.4,
    "upgrade": 0.3,
}

NEGATIVE_KEYWORDS = {
    "hack": -0.9,
    "hacked": -0.9,
    "exploit": -0.8,
    "scam": -0.8,
    "ponzi": -0.9,
    "fraud": -0.8,
    "ban": -0.7,
    "bans": -0.7,
    "crash": -0.8,
    "crashes": -0.8,
    "lawsuit": -0.5,
    "sec charges": -0.7,
    "outflow": -0.4,
    "outflows": -0.4,
    "bearish": -0.6,
    "sell-off": -0.6,
    "selloff": -0.6,
    "liquidations": -0.4,
    "collapse": -0.8,
    "investigation": -0.5,
}


def score_headline(title: str) -> float:
    text = title.lower()
    score = 0.0
    hits = 0
    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword in text:
            score += weight
            hits += 1
    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if keyword in text:
            score += weight
            hits += 1
    if hits == 0:
        return 0.0
    return max(-1.0, min(1.0, score / hits))
