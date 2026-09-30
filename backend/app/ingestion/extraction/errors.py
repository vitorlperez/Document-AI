class ExtractionError(ValueError):
    """Safe, persistable extraction failure; never retains a remote response."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
