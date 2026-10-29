"""Retriever implementations (demo local hybrid / real CSS)."""

from .local_numpy import LocalRetriever
from .css import CssRetriever

__all__ = ["LocalRetriever", "CssRetriever"]
