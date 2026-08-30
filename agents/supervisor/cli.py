"""Running a campaign from the command line, against the real platforms.

    python -m agents.supervisor "Dachdecker" "München" --radius 20
    python -m agents.supervisor "Elektriker" "Rosenheim" --outreach
    python -m agents.supervisor "Elektriker" "Rosenheim" --outreach --send

The three lines do progressively more, and each step needs something the
previous one did not:

    search only        works with no key at all — OpenStreetMap is free, and
                       Google Places joins in if GOOGLE_MAPS_API_KEY is set
    --outreach         needs AGENT_MODE=live and an Anthropic key, because
                       somebody has to write the emails
    --send             needs SMTP credentials *and* a complete sender identity,
                       because a first-contact email that cannot say who sent it
                       has no business being sent

Nothing is ever sent without `--send`. That flag is the only thing in this
repository that turns dry-run off, and it is deliberately the last thing anyone
types rather than a setting they configure once and forget.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agents.outreach.models import Campaign, Language, Sender
from agents.outreach.providers import MailSender, SmtpSender
from agents.outreach.suppression import FileSuppressionList
from agents.prospecting.models import Platform, SearchArea
from agents.prospecting.providers import (
    GooglePlacesProvider,
    HttpPageFetcher,
    MockPages,
    MockPlaces,
    OverpassProvider,
    PlaceProvider,
)
from agents.supervisor.campaign import (
    CampaignResult,
    LeadCampaign,
    lead_sheet,
    outreach_sheet,
    render_summary,
)
from agents.supervisor.scripted import judge_provider
from agents.supervisor.spreadsheet import build_writer
from core.config import Settings
from core.console import configure_stdout
from core.llm import AnthropicProvider, LLMProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.supervisor",
        description="Find businesses in an area and, optionally, write to them.",
    )
    parser.add_argument("what", help='The trade, e.g. "Dachdecker".')
    parser.add_argument("where", help='The place, e.g. "München".')
    parser.add_argument("--radius", type=float, default=20.0, help="Radius in km (default 20).")
    parser.add_argument("--limit", type=int, default=25, help="Maximum businesses (default 25).")
    parser.add_argument("--out", default="leads", help="Directory for the CSV export.")

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run on the fixture platforms instead of the real ones.",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Skip reading company websites. Faster, and finds almost no email addresses.",
    )
    parser.add_argument(
        "--outreach",
        action="store_true",
        help="Draft a first-contact email per business and have the supervisor review it.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the drafts the supervisor approved. Requires --outreach and SMTP.",
    )

    parser.add_argument("--offer", default="", help="What you are offering, in one sentence.")
    parser.add_argument("--goal", default="", help="What a reply would lead to.")
    parser.add_argument(
        "--suppression",
        default="suppression.jsonl",
        help="Do-not-contact list (JSONL). Created on first opt-out.",
    )
    return parser


def build_places(args: argparse.Namespace) -> list[PlaceProvider]:
    """The platforms to search, and a line saying which they turned out to be."""
    if args.mock:
        return [
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ]

    places: list[PlaceProvider] = [OverpassProvider()]
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if api_key:
        places.insert(0, GooglePlacesProvider(api_key))
    return places


def build_sender_identity() -> Sender | None:
    """Who the emails come from, read from the environment.

    Returns None when anything required is missing. The footer has to name a
    company, an address and an imprint; assembling half of one and sending it
    anyway would defeat the point of assembling it in code.
    """
    required = {
        "name": os.environ.get("OUTREACH_SENDER_NAME", "").strip(),
        "company": os.environ.get("OUTREACH_SENDER_COMPANY", "").strip(),
        "email": os.environ.get("OUTREACH_SENDER_EMAIL", "").strip(),
    }
    if not all(required.values()):
        return None

    return Sender(
        **required,
        role=os.environ.get("OUTREACH_SENDER_ROLE", "").strip(),
        website=os.environ.get("OUTREACH_SENDER_WEBSITE", "").strip(),
        address=os.environ.get("OUTREACH_SENDER_ADDRESS", "").strip(),
        imprint_url=os.environ.get("OUTREACH_SENDER_IMPRINT_URL", "").strip(),
        phone=os.environ.get("OUTREACH_SENDER_PHONE", "").strip(),
    )


def build_mail_sender() -> MailSender | None:
    """An SMTP sender, or None when the credentials are not all there."""
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not (host and username and password):
        return None

    return SmtpSender(
        host=host,
        port=int(os.environ.get("SMTP_PORT", "587") or 587),
        username=username,
        password=password,
        use_tls=os.environ.get("SMTP_STARTTLS", "true").strip().lower() != "false",
    )


def run(args: argparse.Namespace, settings: Settings) -> CampaignResult | None:
    """Wire everything up and run one campaign. None means it refused to start."""
    area = SearchArea(
        what=args.what,
        where=args.where,
        radius_km=args.radius,
        limit=args.limit,
    )

    live_model: LLMProvider | None = AnthropicProvider(settings) if settings.is_live else None

    if args.outreach and live_model is None:
        print(
            "--outreach needs a model to write the emails: set AGENT_MODE=live "
            "and ANTHROPIC_API_KEY, or drop the flag to search only.",
            file=sys.stderr,
        )
        return None

    identity = build_sender_identity() if args.outreach else None
    if args.outreach and identity is None:
        print(
            "--outreach needs a sender identity. Set OUTREACH_SENDER_NAME, "
            "OUTREACH_SENDER_COMPANY and OUTREACH_SENDER_EMAIL (see .env.example); "
            "the footer of every email names them.",
            file=sys.stderr,
        )
        return None

    mail_sender = build_mail_sender() if args.send else None
    if args.send and mail_sender is None:
        print(
            "--send needs SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD. Nothing was sent.",
            file=sys.stderr,
        )
        return None

    campaign = Campaign(
        id=f"cli-{area.what.lower().replace(' ', '-')}-{area.where.lower().replace(' ', '-')}",
        sender=identity or Sender(name="—", company="—", email="noreply@invalid.example"),
        goal=args.goal or "Ein kurzes Telefonat.",
        offer=args.offer or "",
        language=Language.DE,
        dry_run=not args.send,
        max_emails=args.limit,
    )

    return LeadCampaign(
        area=area,
        campaign=campaign,
        places=build_places(args),
        pages=(None if args.no_web else (MockPages() if args.mock else HttpPageFetcher())),
        planner=live_model,
        # One client for every draft in live mode. Without --outreach there is
        # no draft provider at all, and the run is a search: no model, no key,
        # nothing written to anybody.
        draft_provider=(lambda _lead: live_model) if args.outreach else None,
        judge=(lambda decisions: live_model) if settings.is_live else judge_provider,
        sender=mail_sender,
        suppression=FileSuppressionList(Path(args.suppression)),
        settings=settings,
    ).run()


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)

    if args.send and not args.outreach:
        print("--send does nothing without --outreach.", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    print(
        f"campaign - mode={settings.mode}  "
        f"platforms={'fixtures' if args.mock else 'live'}  "
        f"outreach={'on' if args.outreach else 'off'}  "
        f"sending={'ON' if args.send else 'dry run'}"
    )

    result = run(args, settings)
    if result is None:
        return 1

    print()
    print(render_summary(result))

    sheets = [lead_sheet(result)]
    if args.outreach:
        sheets.append(outreach_sheet(result))

    destination = Path(args.out) / campaign_slug(result)
    for path in build_writer("csv").write(sheets, destination):
        print(f"\ngeschrieben: {path}")

    return 0


def campaign_slug(result: CampaignResult) -> str:
    """A directory name that says what the run was, without a timestamp.

    Re-running the same area overwrites the previous export on purpose: two
    files a week apart, both called "Dachdecker München", are how a stale lead
    list gets worked by mistake.
    """
    return f"{result.area.what}-{result.area.where}".lower().replace(" ", "-")


if __name__ == "__main__":
    raise SystemExit(main())
