"""Tests for the Obsidian vault writer.

This is the one integration in the repository that can be tested for real: a
vault is a folder of Markdown files, so there is no account to stand in for
and no skeleton to apologise for.
"""

from __future__ import annotations

from console.models import VaultNote
from console.vault import MemoryVault, ObsidianVault, render_note, safe_slug


def note(**overrides) -> VaultNote:
    base = {
        "slug": "dec-email-msg-001",
        "folder": "Decisions",
        "title": "Question about bulk pricing",
        "frontmatter": {"type": "decision", "verdict": "approved", "cost_usd": 0.0026},
        "body": "A routine enquiry.",
        "links": ["Agent email-triage", "2026-03-06 Brief"],
    }
    return VaultNote(**{**base, **overrides})


# --- Slugs --------------------------------------------------------------


def test_windows_forbidden_characters_are_stripped():
    # A note whose name contains any of these either fails to write on Windows
    # or silently breaks every link pointing at it.
    assert safe_slug('RE: order <A/1044> | "urgent"?') == "RE order A1044 urgent"


def test_obsidian_link_syntax_is_stripped():
    assert safe_slug("Call [[call-001]] #urgent") == "Call call-001 urgent"


def test_long_names_are_truncated_without_a_trailing_dot():
    slug = safe_slug("x" * 200)
    assert len(slug) == 80
    assert not slug.endswith(".")


def test_a_name_that_sanitises_to_nothing_still_gets_a_filename():
    assert safe_slug("///???") == "untitled"


def test_ordinary_names_are_left_alone():
    assert safe_slug("2026-03-06 Brief") == "2026-03-06 Brief"


# --- Rendering ----------------------------------------------------------


def test_a_note_opens_with_yaml_frontmatter():
    text = render_note(note())
    assert text.startswith("---\n")
    assert "type: decision" in text
    assert "verdict: approved" in text


def test_numbers_are_written_unquoted_so_dataview_can_use_them():
    assert "cost_usd: 0.0026" in render_note(note())


def test_lists_are_written_as_yaml_arrays():
    text = render_note(note(frontmatter={"tags": ["codex", "blocked"]}))
    assert 'tags: ["codex", "blocked"]' in text


def test_values_needing_quotes_get_them():
    text = render_note(note(frontmatter={"title": "RE: something"}))
    assert 'title: "RE: something"' in text


def test_booleans_are_yaml_booleans_not_python_ones():
    text = render_note(note(frontmatter={"sent": False}))
    assert "sent: false" in text


def test_links_are_rendered_as_wikilinks():
    text = render_note(note())
    assert "- [[Agent email-triage]]" in text
    assert "- [[2026-03-06 Brief]]" in text


def test_a_note_without_links_has_no_linked_section():
    assert "## Linked" not in render_note(note(links=[]))


# --- Writing ------------------------------------------------------------


def test_a_note_lands_in_its_folder(tmp_path):
    path = ObsidianVault(tmp_path).write(note())

    assert (tmp_path / "Decisions" / "dec-email-msg-001.md").exists()
    assert path.endswith("dec-email-msg-001.md")


def test_writing_the_same_note_twice_updates_rather_than_duplicates(tmp_path):
    # An audit trail that grows a second copy on every run is one nobody trusts.
    vault = ObsidianVault(tmp_path)
    vault.write(note())
    vault.write(note(body="Revised."))

    files = list((tmp_path / "Decisions").glob("*.md"))
    assert len(files) == 1
    assert "Revised." in files[0].read_text(encoding="utf-8")


def test_folders_are_created_as_needed(tmp_path):
    ObsidianVault(tmp_path / "deep" / "nested").write(note())
    assert (tmp_path / "deep" / "nested" / "Decisions" / "dec-email-msg-001.md").exists()


def test_an_unsafe_title_still_produces_a_writable_file(tmp_path):
    ObsidianVault(tmp_path).write(note(slug="RE: <urgent> | order?"))
    assert list((tmp_path / "Decisions").glob("*.md"))


def test_notes_are_written_as_utf8(tmp_path):
    vault = ObsidianVault(tmp_path)
    written = note(body="Rückfrage zur Rechnung — über 4.180 €")
    vault.write(written)

    assert "Rückfrage" in vault.read(written)


def test_the_vault_records_what_it_wrote(tmp_path):
    vault = ObsidianVault(tmp_path)
    vault.write(note(slug="a"))
    vault.write(note(slug="b"))

    assert len(vault.written) == 2


# --- Memory vault -------------------------------------------------------


def test_the_memory_vault_touches_no_filesystem():
    vault = MemoryVault()
    key = vault.write(note())

    assert key == "Decisions/dec-email-msg-001.md"
    assert "# Question about bulk pricing" in vault.notes[key]


def test_the_memory_vault_also_updates_in_place():
    vault = MemoryVault()
    vault.write(note())
    vault.write(note(body="Revised."))

    assert len(vault.written) == 1
