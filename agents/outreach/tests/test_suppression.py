"""Tests for the do-not-contact list."""

from __future__ import annotations

from pathlib import Path

from agents.outreach.suppression import (
    FileSuppressionList,
    MemorySuppressionList,
    SuppressionEntry,
)


def test_an_exact_address_is_blocked():
    suppression = MemorySuppressionList(["info@reiter.example"])

    assert suppression.blocks("info@reiter.example") is not None
    assert suppression.blocks("m.reiter@reiter.example") is None


def test_a_domain_entry_covers_every_mailbox_at_the_firm():
    suppression = MemorySuppressionList(["@reiter.example"])

    assert suppression.blocks("m.reiter@reiter.example") is not None
    assert suppression.blocks("info@other.example") is None


def test_matching_ignores_case_and_whitespace():
    suppression = MemorySuppressionList(["info@reiter.example"])

    assert suppression.blocks("  INFO@Reiter.example ") is not None


def test_the_reason_travels_with_the_entry():
    suppression = MemorySuppressionList(
        [SuppressionEntry(value="info@reiter.example", reason="hat 2025 widersprochen")]
    )
    blocked = suppression.blocks("info@reiter.example")

    assert blocked is not None
    assert blocked.reason == "hat 2025 widersprochen"


def test_an_entry_added_now_blocks_immediately(tmp_path: Path):
    suppression = FileSuppressionList(tmp_path / "suppression.jsonl")
    suppression.add("info@reiter.example", "hat um Löschung gebeten")

    assert suppression.blocks("info@reiter.example") is not None


def test_entries_survive_a_restart(tmp_path: Path):
    path = tmp_path / "suppression.jsonl"
    FileSuppressionList(path).add("info@reiter.example", "abgemeldet")

    assert FileSuppressionList(path).blocks("info@reiter.example") is not None


def test_a_missing_file_is_an_empty_list_rather_than_a_crash(tmp_path: Path):
    assert FileSuppressionList(tmp_path / "nothing.jsonl").entries == []


def test_a_hand_edited_broken_line_does_not_take_the_list_down(tmp_path: Path):
    """The failure that matters: refusing to start means running with no list."""
    path = tmp_path / "suppression.jsonl"
    path.write_text(
        '{"value": "info@reiter.example"}\nnot json at all\n{"value": "@other.example"}\n',
        encoding="utf-8",
    )
    suppression = FileSuppressionList(path)

    assert len(suppression.entries) == 2
    assert suppression.blocks("anyone@other.example") is not None


def test_comments_are_allowed_in_the_file(tmp_path: Path):
    path = tmp_path / "suppression.jsonl"
    path.write_text('# opted out by phone\n{"value": "info@reiter.example"}\n', encoding="utf-8")

    assert len(FileSuppressionList(path).entries) == 1
