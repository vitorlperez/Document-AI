class SourceRemoteUnauthorized(RuntimeError):
    """A connected source rejected its delegated credentials."""


class SourceItemUnavailable(RuntimeError):
    """One remote item (file/page) cannot be read; the source itself is still authorized."""

    def __init__(self, reason: str = "unavailable"):
        super().__init__(reason)
        self.reason = reason
