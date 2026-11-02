"""Errors shared by the ci-scope command line tools."""


class CliError(RuntimeError):
    pass


class NotRegisteredError(CliError):
    """The server has no config for this repository."""
