"""Tests for the `.env` loader.

`.env.example` told people to copy it to `.env` long before anything read the
result. That is a worse failure than no support at all — the instruction looked
followed and every setting silently stayed at its default — so the precedence
rule and the parsing both get pinned down here.
"""

from __future__ import annotations

import os

from core.dotenv import load, parse


def test_a_plain_assignment_is_parsed():
    assert parse("KEY=value") == {"KEY": "value"}


def test_comments_and_blank_lines_are_ignored():
    text = "# a comment\n\nKEY=value\n   \n# another\n"
    assert parse(text) == {"KEY": "value"}


def test_an_export_prefix_is_accepted():
    # People paste lines out of their shell profile.
    assert parse("export KEY=value") == {"KEY": "value"}


def test_surrounding_quotes_are_stripped():
    assert parse('KEY="value"') == {"KEY": "value"}
    assert parse("KEY='value'") == {"KEY": "value"}


def test_an_unquoted_windows_path_with_spaces_survives():
    # The case this was written for: OBSIDIAN_VAULT_PATH points at a folder
    # whose name contains a space, and quoting it should not be required.
    text = r"OBSIDIAN_VAULT_PATH=D:\Claude\Alija Vault\Alija Vault"
    assert parse(text) == {"OBSIDIAN_VAULT_PATH": r"D:\Claude\Alija Vault\Alija Vault"}


def test_a_value_containing_an_equals_sign_is_kept_whole():
    assert parse("KEY=a=b=c") == {"KEY": "a=b=c"}


def test_an_empty_value_is_allowed():
    assert parse("KEY=") == {"KEY": ""}


def test_a_line_without_an_equals_sign_is_skipped():
    assert parse("not an assignment\nKEY=value") == {"KEY": "value"}


def test_a_line_with_no_key_is_skipped():
    assert parse("=orphan\nKEY=value") == {"KEY": "value"}


# --- Loading ------------------------------------------------------------


def test_loading_sets_the_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EXAMPLE_SETTING=from-file", encoding="utf-8")
    monkeypatch.delenv("EXAMPLE_SETTING", raising=False)

    assert load(env) == {"EXAMPLE_SETTING": "from-file"}
    assert os.environ["EXAMPLE_SETTING"] == "from-file"


def test_the_real_environment_wins(tmp_path, monkeypatch):
    # CI sets variables deliberately, and a stale .env on somebody's machine
    # must never quietly override them.
    env = tmp_path / ".env"
    env.write_text("EXAMPLE_SETTING=from-file", encoding="utf-8")
    monkeypatch.setenv("EXAMPLE_SETTING", "from-environment")

    assert load(env) == {}
    assert os.environ["EXAMPLE_SETTING"] == "from-environment"


def test_override_is_available_when_asked_for(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EXAMPLE_SETTING=from-file", encoding="utf-8")
    monkeypatch.setenv("EXAMPLE_SETTING", "from-environment")

    load(env, override=True)
    assert os.environ["EXAMPLE_SETTING"] == "from-file"


def test_a_missing_file_is_not_an_error(tmp_path):
    # The whole repository runs on defaults; demanding a .env would break the
    # promise that a fresh clone works.
    assert load(tmp_path / "nothing-here") == {}


def test_settings_pick_up_a_dotenv(tmp_path, monkeypatch):
    from core.config import Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MAX_STEPS", raising=False)
    (tmp_path / ".env").write_text("AGENT_MAX_STEPS=42", encoding="utf-8")

    assert Settings.from_env().max_steps == 42


def test_an_explicit_environment_still_beats_a_dotenv(tmp_path, monkeypatch):
    from core.config import Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")
    (tmp_path / ".env").write_text("AGENT_MAX_STEPS=42", encoding="utf-8")

    assert Settings.from_env().max_steps == 7


def test_a_file_saved_by_notepad_still_works(tmp_path, monkeypatch):
    """Windows editors write a byte order mark; it must not reach the parser.

    Under plain utf-8 the mark becomes part of the first line, which either
    stops a leading comment from being recognised as one or, if the file starts
    with a setting, glues itself to the key name so the value silently never
    applies.
    """
    env = tmp_path / ".env"
    env.write_text("EXAMPLE_SETTING=works", encoding="utf-8-sig")
    monkeypatch.delenv("EXAMPLE_SETTING", raising=False)

    assert load(env) == {"EXAMPLE_SETTING": "works"}


def test_windows_line_endings_are_handled(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_bytes(b"# comment\r\nEXAMPLE_SETTING=works\r\n")
    monkeypatch.delenv("EXAMPLE_SETTING", raising=False)

    assert load(env) == {"EXAMPLE_SETTING": "works"}
