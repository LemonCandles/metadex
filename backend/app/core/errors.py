"""Stable error categories used across collection and processing stages."""


class MetadexError(Exception):
    """Base class for expected, classifiable application failures."""


class RecoverableError(MetadexError):
    """A temporary failure that a caller may retry under a bounded policy."""


class DataError(MetadexError):
    """Invalid or inconsistent input that must be measured and rejected."""


class PermanentError(MetadexError):
    """A failure that retries cannot fix, such as invalid authentication."""
