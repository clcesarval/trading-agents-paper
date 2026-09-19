class MarketDataError(Exception):
    """Base class for classified market-data failures."""


class ConnectionFailed(MarketDataError):
    pass


class RequestTimedOut(MarketDataError):
    pass


class RateLimited(MarketDataError):
    pass


class InvalidTicker(MarketDataError):
    pass


class HttpStatusError(MarketDataError):
    pass


class EmptyResponse(MarketDataError):
    pass


def classify_httpx_error(exc: Exception, source: str, ticker: str) -> MarketDataError:
    import httpx

    if isinstance(exc, httpx.ConnectError):
        return ConnectionFailed(f"{source}: falha de conexão para {ticker}: {exc}")
    if isinstance(exc, httpx.TimeoutException):
        return RequestTimedOut(f"{source}: tempo esgotado consultando {ticker}: {exc}")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return RateLimited(f"{source}: limite de requisições atingido (429) para {ticker}")
        if status == 404:
            return InvalidTicker(f"{source}: ticker {ticker} não encontrado (404)")
        return HttpStatusError(f"{source}: resposta HTTP {status} para {ticker}")
    return MarketDataError(f"{source}: {type(exc).__name__}: {exc}")
