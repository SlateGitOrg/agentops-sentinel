"""Exceptions raised by domain tools."""

from __future__ import annotations


class ToolError(Exception):
    """A tool call failed unexpectedly (simulated transient backend error)."""


class ToolNotFoundError(ToolError):
    """The tool ran fine but found no matching record (e.g. unknown order)."""
