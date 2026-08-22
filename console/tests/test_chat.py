"""Tests for the operator chat.

Three things carry the design and get the most coverage: that a clarification
is a pause rather than a handover, that the brain answers what the codex
already settles, and that a task typed into the console is reviewed exactly
like one an agent raised itself.
"""

from __future__ import annotations

import pytest

from agents.brain.models import DecisionKind, Judgement, Verdict
from agents.brain.supervisor import BrainAgent
from console.chat import ChatSession, RoutingDecision, brain_answer
from console.chat_demo import build_session, run
from console.handlers import TaskOutcome, find_company, to_decision
from console.scripted import REQUESTS
from console.tasks import Conversation, Question, Speaker, Task, TaskStatus
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def routes(*decisions: RoutingDecision) -> MockProvider:
    """A scripted router.

    Falls back to a single unusable decision when a test supplies none: those
    tests never get as far as routing, and a genuinely empty provider is
    rejected by MockProvider — correctly, since running out of responses is a
    failure worth hearing about everywhere else.
    """
    scripted = decisions or (RoutingDecision(agent="none", reason="not reached in this test"),)
    return MockProvider(
        [text_response(d.model_dump_json()) for d in scripted], model="claude-opus-5"
    )


def brain(count: int = 6) -> BrainAgent:
    return BrainAgent(
        provider=MockProvider(
            [text_response(Judgement().model_dump_json()) for _ in range(count)],
            model="claude-opus-5",
        ),
        settings=settings(),
    )


class StubHandler:
    """An agent that returns whatever the test tells it to."""

    agent = "stub"
    capability = "does whatever the test needs"

    def __init__(self, *outcomes: TaskOutcome) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def handle(self, task: Task) -> TaskOutcome:
        self.calls.append(task.briefing)
        return self._outcomes.pop(0) if self._outcomes else TaskOutcome(summary="done")


def session_with(handler, *decisions: RoutingDecision) -> ChatSession:
    return ChatSession(
        handlers=[handler],
        router_provider=routes(*decisions),
        brain=brain(),
        settings=settings(),
    )


def to_stub(reason: str = "the only agent") -> RoutingDecision:
    return RoutingDecision(agent="stub", reason=reason)


# --- Routing ------------------------------------------------------------


def test_a_routed_request_reaches_the_agent():
    handler = StubHandler(TaskOutcome(summary="did the thing"))
    task = session_with(handler, to_stub()).submit("do the thing")

    assert task.agent == "stub"
    assert handler.calls == ["do the thing"]
    assert task.result == "did the thing"


def test_a_model_naming_an_agent_that_does_not_exist_is_not_obeyed():
    # The router proposes; this validates. A hallucinated agent name must not
    # send work anywhere.
    handler = StubHandler()
    task = session_with(handler, RoutingDecision(agent="ghost", reason="made up")).submit("x")

    assert task.agent is None
    assert task.status is TaskStatus.UNROUTABLE
    assert handler.calls == []


def test_an_unplaceable_request_asks_rather_than_guessing():
    task = session_with(
        StubHandler(), RoutingDecision(agent="none", reason="no agent does facilities")
    ).submit("sort out the parking")

    assert task.status is TaskStatus.UNROUTABLE
    assert task.open_questions
    assert "stub" in task.open_questions[0].options


def test_naming_the_agent_resumes_an_unroutable_task():
    handler = StubHandler(TaskOutcome(summary="finished"))
    session = session_with(
        handler, RoutingDecision(agent="none", reason="unclear"), to_stub("operator said so")
    )
    task = session.submit("something vague")
    session.answer(task.id, task.open_questions[0].id, "stub")

    assert task.agent == "stub"
    assert task.status is TaskStatus.DONE


def test_an_empty_request_is_refused_without_routing():
    session = session_with(StubHandler())
    task = session.submit("   ")

    assert task.status is TaskStatus.FAILED
    assert task.error == "empty request"


def test_a_session_needs_at_least_one_agent():
    with pytest.raises(ValueError, match="at least one agent"):
        ChatSession(handlers=[], router_provider=routes(), brain=brain(), settings=settings())


# --- Clarification ------------------------------------------------------


def a_question(text: str = "Which one?", why: str = "I cannot tell.") -> Question:
    return Question(id="q1", text=text, why=why, options=["a", "b"])


def test_a_question_pauses_the_task_rather_than_handing_it_over():
    # The distinction the whole status enum exists for: the task is still the
    # agent's, waiting, not escalated to a person to finish.
    handler = StubHandler(TaskOutcome(questions=[a_question()]))
    task = session_with(handler, to_stub()).submit("ambiguous")

    assert task.status is TaskStatus.NEEDS_CLARIFICATION
    assert task.status.is_open
    assert task.status.waits_on_operator
    assert task.status is not TaskStatus.ESCALATED


def test_answering_resumes_the_same_task():
    handler = StubHandler(TaskOutcome(questions=[a_question()]), TaskOutcome(summary="now I can"))
    session = session_with(handler, to_stub())
    task = session.submit("ambiguous")
    session.answer(task.id, "q1", "the first one")

    assert task.status is TaskStatus.DONE
    assert task.result == "now I can"
    assert len(handler.calls) == 2


def test_the_answer_reaches_the_agent_as_labelled_context():
    # Appended as clarification rather than merged into the request, so nothing
    # in an answer can be mistaken for the original instruction.
    handler = StubHandler(TaskOutcome(questions=[a_question()]), TaskOutcome(summary="ok"))
    session = session_with(handler, to_stub())
    task = session.submit("do it")
    session.answer(task.id, "q1", "the blue one")

    second = handler.calls[1]
    assert second.startswith("do it")
    assert "The operator has since clarified:" in second
    assert "the blue one" in second


def test_answering_a_closed_question_changes_nothing():
    handler = StubHandler(TaskOutcome(questions=[a_question()]), TaskOutcome(summary="ok"))
    session = session_with(handler, to_stub())
    task = session.submit("do it")
    session.answer(task.id, "q1", "first answer")

    before = len(task.answers)
    session.answer(task.id, "q1", "second answer, steering elsewhere")

    assert len(task.answers) == before
    assert any("already answered" in turn.text for turn in session.conversation.turns)


def test_an_unknown_task_returns_nothing():
    assert session_with(StubHandler()).answer("task-nope", "q1", "x") is None


def test_several_questions_all_have_to_be_answered():
    questions = [
        Question(id="q1", text="First?", why="a"),
        Question(id="q2", text="Second?", why="b"),
    ]
    handler = StubHandler(TaskOutcome(questions=questions), TaskOutcome(summary="ok"))
    session = session_with(handler, to_stub())
    task = session.submit("do it")

    session.answer(task.id, "q1", "one")
    assert task.status is TaskStatus.NEEDS_CLARIFICATION

    session.answer(task.id, "q2", "two")
    assert task.status is TaskStatus.DONE


# --- The brain answering first -----------------------------------------


def test_the_brain_settles_a_policy_question_without_asking_the_operator():
    settled = brain_answer(
        Question(
            id="q",
            text="May I send this to the address even though it is unconfirmed?",
            why="The caller never spelled it out.",
        )
    )
    assert settled is not None
    article, ruling = settled
    assert article == "A4"
    assert "confirmed" in ruling


def test_a_question_no_rule_covers_goes_to_the_operator():
    assert (
        brain_answer(
            Question(
                id="q",
                text="Which of the two Berlin warehouses ships this?",
                why="The document names both.",
            )
        )
        is None
    )


def test_a_settled_question_never_reaches_the_operator():
    policy_question = Question(
        id="q1",
        text="Can I quote the discount in the reply?",
        why="The customer asked for a price.",
    )
    handler = StubHandler(TaskOutcome(questions=[policy_question]), TaskOutcome(summary="ok"))
    session = session_with(handler, to_stub())
    task = session.submit("reply to them")

    assert task.open_questions == []
    assert task.status is TaskStatus.DONE
    assert any(turn.speaker is Speaker.BRAIN for turn in session.conversation.turns)


def test_a_settled_question_is_still_recorded():
    # Answered by the brain, not erased — the exchange stays in the transcript
    # and the ruling reaches the agent's next briefing.
    policy_question = Question(
        id="q1", text="Can I quote the price?", why="They asked for a discount."
    )
    handler = StubHandler(TaskOutcome(questions=[policy_question]), TaskOutcome(summary="ok"))
    session = session_with(handler, to_stub())
    task = session.submit("reply")

    assert len(task.questions) == 1
    assert len(task.answers) == 1
    assert "A3" in task.answers[0].text


# --- Review -------------------------------------------------------------


def test_a_result_goes_through_the_codex():
    handler = StubHandler(
        TaskOutcome(
            summary="drafted a reply",
            kind=DecisionKind.SEND_EMAIL,
            outbound_text="We guarantee a 20% discount, act now.",
            recipient="someone@example.test",
            recipient_verified=True,
        )
    )
    task = session_with(handler, to_stub()).submit("write to them")

    assert task.status is TaskStatus.ESCALATED
    assert task.verdict == Verdict.HOLD_FOR_HUMAN.label
    assert any("A3" in reason or "A6" in reason for reason in task.review_reasons)


def test_the_console_cannot_produce_an_approval_the_codex_refuses():
    # The property that makes the chat safe to add at all.
    handler = StubHandler(
        TaskOutcome(
            summary="sent it",
            kind=DecisionKind.SEND_EMAIL,
            outbound_text="Here you go.",
            recipient="invented@example.test",
            recipient_verified=False,
        )
    )
    task = session_with(handler, to_stub()).submit("mail them")

    assert task.status is TaskStatus.BLOCKED
    assert task.verdict == Verdict.BLOCKED.label


def test_a_chat_task_becomes_an_ordinary_decision():
    task = Task(id="t1", request="do something", agent="stub")
    decision = to_decision(task, TaskOutcome(summary="s", requires_human=True))

    assert decision.agent == "stub"
    assert decision.trace_ref == "t1"
    assert decision.requires_human is True


def test_a_crashing_agent_fails_the_task_rather_than_the_session():
    class Exploding:
        agent = "stub"
        capability = "raises"

        def handle(self, task):
            raise RuntimeError("boom")

    task = session_with(Exploding(), to_stub()).submit("go")

    assert task.status is TaskStatus.FAILED
    assert "boom" in (task.error or "")


# --- Company extraction -------------------------------------------------


def test_a_named_company_is_found():
    assert find_company("research Kestrel Systems please", ["Kestrel Systems"]) == "Kestrel Systems"


def test_no_company_named_returns_nothing():
    assert find_company("research our biggest account", ["Kestrel Systems"]) is None


def test_two_companies_named_is_ambiguous_not_a_guess():
    known = ["Kestrel Systems", "Halvard Marine"]
    assert find_company("compare Kestrel Systems and Halvard Marine", known) is None


# --- The demo -----------------------------------------------------------


def test_the_demo_covers_every_outcome():
    session = run(settings())
    statuses = {task.status for task in session.conversation.tasks}

    assert TaskStatus.DONE in statuses
    assert TaskStatus.UNROUTABLE in statuses
    assert len(session.conversation.tasks) == len(REQUESTS)


def test_the_demo_shows_a_clarification_round_trip():
    session = run(settings())
    answered = [t for t in session.conversation.tasks if t.answers and t.status is TaskStatus.DONE]

    assert answered
    assert answered[0].questions


def test_the_conversation_records_who_said_what():
    speakers = {turn.speaker for turn in run(settings()).conversation.turns}
    assert Speaker.OPERATOR in speakers
    assert Speaker.AGENT in speakers
    assert Speaker.BRAIN in speakers


def test_building_a_session_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert build_session(settings()) is not None


def test_an_empty_conversation_has_nothing_open():
    conversation = Conversation(id="c1")
    assert conversation.open_count == 0
    assert conversation.waiting == []
    assert conversation.total_cost_usd == 0.0
