"""Tests for the stdout widening used by every demo."""

from __future__ import annotations

import io
import sys

from core.console import configure_stdout


def test_configure_stdout_widens_a_narrow_stream(monkeypatch):
    # A pipe on a German Windows install gives cp1252, which cannot encode the
    # emoji in the spam fixture. Before this helper existed the demo died there.
    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", narrow)

    configure_stdout()

    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
    print("\U0001f680 rocket")  # would raise UnicodeEncodeError under cp1252


def test_configure_stdout_tolerates_a_stream_it_cannot_reconfigure(monkeypatch):
    class Fixed:
        encoding = "ascii"

        def write(self, _text: str) -> int:
            return 0

    monkeypatch.setattr(sys, "stdout", Fixed())
    monkeypatch.setattr(sys, "stderr", Fixed())

    # Setting up to print must never be the thing that fails.
    configure_stdout()


def test_configure_stdout_is_idempotent(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    configure_stdout()
    configure_stdout()

    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
