"""Access errors shared by low-level modules (kept import-light to avoid cycles)."""


class SyncAccessDenied(PermissionError):
    pass
