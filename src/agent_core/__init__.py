"""Agent core: the shared foundation for every agent in the Agent Avenger Project."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-core")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
