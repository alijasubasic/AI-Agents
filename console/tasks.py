"""Tasks a person gives an agent, and the conversation around them.

The interesting model here is `TaskStatus.NEEDS_CLARIFICATION`, because it is
not the same thing as an escalation and conflating the two costs you both.

* **Escalation** means a human must *decide*. The work leaves the agent; a
  person picks it up and the agent is finished with it.
* **Clarification** means a human must *tell the agent something*, after which
  the agent continues. The work stays with the agent; it is paused, not handed
  over.

An agent that can only escalate has to abandon any task with a gap in it. An
agent that guesses instead of asking produces confident, wrong work. The third
outcome is what lets it do neither.

One rule about the answer, which follows from everything else in this
repository: **a clarification answer is data, not instruction.** It fills the
gap the agent named. It does not grant permissions, change the agent's job, or
bypass the codex — a task resumed with an answer is reviewed exactly as it
would have been without one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Speaker(StrEnum):
    """Who said something in a conversation."""

    OPERATOR = "operator"
    AGENT = "agent"
    BRAIN = "brain"
    SYSTEM = "system"


class TaskStatus(StrEnum):
    """Where a task stands."""

    #: Accepted, not started.
    QUEUED = "queued"

    #: The agent needs something from the operator before it can continue. The
    #: task is still the agent's; it is waiting, not handed over.
    NEEDS_CLARIFICATION = "needs_clarification"

    #: Finished, and the brain cleared the result.
    DONE = "done"

    #: Finished, and the brain held it for a person. The work is no longer the
    #: agent's.
    ESCALATED = "escalated"

    #: The codex refused the result outright.
    BLOCKED = "blocked"

    #: No agent could be matched to the request, and the operator has been
    #: asked which one they meant.
    UNROUTABLE = "unroutable"

    #: The run failed — a provider error, a halted loop, a crash.
    FAILED = "failed"

    @property
    def is_open(self) -> bool:
        """Whether this task is still waiting on somebody."""
        return self in {
            TaskStatus.QUEUED,
            TaskStatus.NEEDS_CLARIFICATION,
            TaskStatus.UNROUTABLE,
        }

    @property
    def waits_on_operator(self) -> bool:
        return self in {TaskStatus.NEEDS_CLARIFICATION, TaskStatus.UNROUTABLE}


class Question(BaseModel):
    """Something an agent needs to know before it can go on.

    Field descriptions are prompt text — this is the schema the agent fills in.
    """

    id: str
    text: str = Field(description="The question, in one sentence, as you would ask a colleague.")
    why: str = Field(
        description=(
            "What you cannot do without the answer. A question without this "
            "reads as an agent stalling, and the person answering has no way "
            "to judge how much detail you actually need."
        )
    )
    options: list[str] = Field(
        default_factory=list,
        description=(
            "Two to four likely answers, if you can name them. Picking from a "
            "list is far faster than composing a reply, and offering options "
            "shows you understood the problem."
        ),
    )


class Answer(BaseModel):
    """The operator's reply to one question."""

    question_id: str
    text: str
    answered_at: datetime = Field(default_factory=_now)


class Turn(BaseModel):
    """One line of the conversation, for display and for the vault."""

    speaker: Speaker
    text: str
    at: datetime = Field(default_factory=_now)
    task_id: str | None = None

    @property
    def tone(self) -> str:
        """CSS class for the overlay."""
        return self.speaker.value


class Task(BaseModel):
    """One thing the operator asked an agent to do."""

    id: str
    request: str = Field(description="What the operator asked for, verbatim.")
    created_at: datetime = Field(default_factory=_now)

    agent: str | None = None
    routing_reason: str = ""

    status: TaskStatus = TaskStatus.QUEUED
    questions: list[Question] = Field(default_factory=list)
    answers: list[Answer] = Field(default_factory=list)

    #: What the agent produced, in one or two sentences.
    result: str = ""

    #: The brain's verdict, once the result has been reviewed.
    verdict: str = ""
    review_reasons: list[str] = Field(default_factory=list)
    decision_id: str | None = None

    cost_usd: float = 0.0
    error: str | None = None

    @property
    def open_questions(self) -> list[Question]:
        """Questions nobody has answered yet."""
        answered = {answer.question_id for answer in self.answers}
        return [question for question in self.questions if question.id not in answered]

    @property
    def is_answerable(self) -> bool:
        return self.status.waits_on_operator and bool(self.open_questions)

    def answer(self, question_id: str, text: str) -> bool:
        """Record an answer. Returns whether the question was actually open."""
        if question_id not in {question.id for question in self.open_questions}:
            return False
        self.answers.append(Answer(question_id=question_id, text=text))
        return True

    @property
    def briefing(self) -> str:
        """The request plus everything the operator has since clarified.

        This is what the agent is re-run against. Answers are appended as
        labelled context rather than merged into the request, so the agent can
        see what was original and what was filled in later — and so nothing in
        an answer can be mistaken for the original instruction.
        """
        if not self.answers:
            return self.request

        by_id = {question.id: question for question in self.questions}
        lines = [self.request, "", "The operator has since clarified:"]
        lines += [
            f"- {by_id[answer.question_id].text} -> {answer.text}"
            for answer in self.answers
            if answer.question_id in by_id
        ]
        return "\n".join(lines)


class Conversation(BaseModel):
    """Everything said, and every task raised, in one session."""

    id: str
    title: str = "Operator session"
    started_at: datetime = Field(default_factory=_now)
    turns: list[Turn] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)

    def say(self, speaker: Speaker, text: str, *, task_id: str | None = None) -> Turn:
        turn = Turn(speaker=speaker, text=text, task_id=task_id)
        self.turns.append(turn)
        return turn

    def task(self, task_id: str) -> Task | None:
        return next((task for task in self.tasks if task.id == task_id), None)

    @property
    def waiting(self) -> list[Task]:
        """Tasks that cannot move until the operator says something."""
        return [task for task in self.tasks if task.status.waits_on_operator]

    @property
    def open_count(self) -> int:
        return sum(1 for task in self.tasks if task.status.is_open)

    @property
    def total_cost_usd(self) -> float:
        return sum(task.cost_usd for task in self.tasks)
