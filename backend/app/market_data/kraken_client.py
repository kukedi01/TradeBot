import ccxt

kraken = ccxt.kraken()


def get_ticker_price(symbol: str) -> float:
    ticker = kraken.fetch_ticker(symbol)
    return ticker["last"]
