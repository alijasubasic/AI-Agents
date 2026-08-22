"""The console demo is documented in the README, so a test keeps it honest.

The important assertion here is the one about blocked decisions: three separate
surfaces describe the same day, and none of them may describe a refused action
as though it happened.
"""

from __future__ import annotations

from agents.brain.models import Verdict
from console import demo
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_the_demo_runs_all_three_layers(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    report, voice, vault = demo.run(_settings())

    assert report.reviews
    assert voice.transcript
    assert vault.written


def test_the_briefing_never_reports_a_blocked_decision_as_done(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    report, voice, _vault = demo.run(_settings())

    blocked = [r for r in report.reviews if r.verdict is Verdict.BLOCKED]
    assert blocked

    for review in blocked:
        # Every mention of a blocked decision must carry the word "blocked".
        mentions = [line for line in voice.transcript if review.decision.subject in line]
        assert mentions
        assert all("Blocked:" in line for line in mentions)


def test_speaking_stops_cleanly_when_the_budget_runs_out(tmp_path, monkeypatch):
    from console.voice import MockVoice

    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    report = demo.brain_demo.run(_settings())

    tight = MockVoice(budget=40)
    clips = demo.speak_briefing(report, tight)

    # The run reports the failure and stops speaking; it does not raise, and it
    # does not silently continue billing.
    assert any(clip.error for clip in clips)
    assert tight.characters_used <= 40


def test_every_decision_reaches_the_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    report, _voice, vault = demo.run(_settings())

    decisions = [p for p in vault.written if p.parent.name == "Decisions"]
    assert len(decisions) == len(report.reviews)


def test_the_vault_records_a_block_as_a_block(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    report, _voice, vault = demo.run(_settings())

    blocked = next(r for r in report.reviews if r.verdict is Verdict.BLOCKED)
    note = next(p for p in vault.written if p.stem == blocked.decision.id)
    text = note.read_text(encoding="utf-8")

    assert "verdict: blocked" in text
    if blocked.decision.outbound_text:
        assert "was **not** sent" in text


def test_rerunning_the_demo_does_not_duplicate_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    demo.run(_settings())
    first = sorted(p.name for p in (tmp_path / "vault" / "Decisions").glob("*.md"))

    demo.run(_settings())
    second = sorted(p.name for p in (tmp_path / "vault" / "Decisions").glob("*.md"))

    assert first == second


def test_demo_main_runs_without_any_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(demo, "DEFAULT_VAULT_PATH", tmp_path / "vault")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.setattr(demo, "OVERLAY_PATH", tmp_path / "overlay.html")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "console demo" in output
    assert (tmp_path / "overlay.html").exists()
    assert "Nothing the codex refused" in output


def test_an_explicit_vault_path_beats_the_environment(tmp_path, monkeypatch):
    """The guard against a test writing into somebody's real notes.

    `OBSIDIAN_VAULT_PATH` is set on the machine this repository was developed
    on. With the environment read deep inside `run`, any test that forgot to
    clear it would have written 24 notes into a real Obsidian vault and said
    nothing about it.
    """
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "must-not-be-used"))
    target = tmp_path / "chosen"

    demo.run(Settings(trace_enabled=False), vault_path=target)

    assert list(target.rglob("*.md"))
    assert not (tmp_path / "must-not-be-used").exists()


def test_the_environment_is_used_when_no_path_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "from-env"))
    assert demo.resolve_vault_path() == tmp_path / "from-env"


def test_the_local_sandbox_is_the_last_resort(monkeypatch):
    # A clone with nothing configured must never write outside itself.
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert demo.resolve_vault_path() == demo.DEFAULT_VAULT_PATH
