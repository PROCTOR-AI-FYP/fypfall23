"""Penalty notice drafting via the Claude API, with a deterministic fallback.

Exactly one API call per penalty issuance: the client has max_retries=0,
nothing here loops, and callers invoke this only from the issuance path
(reads return the stored document). If the call fails or is declined, the
notice is rendered from a local template instead of retrying.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.config import settings
from app.models import NoticeSource

logger = logging.getLogger("proctorai.notices")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
FALLBACK_TEMPLATE = "penalty_notice.txt"
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_OUTPUT_TOKENS = 16000

SYSTEM_PROMPT = (
    "You draft formal academic-integrity penalty notices for a university examinations office. "
    "Use only the facts in the case record you are given; never invent evidence, dates, names, or outcomes. "
    "Write in a neutral, factual register: the notice informs the student of a decision and of their right "
    "to appeal, and must not read as punitive. Output plain text with no markdown. Include the notice "
    "reference, the course, the examination date and room, the behaviours recorded by the proctoring "
    "system, the penalty decided by the Head of Department with its description, and a closing paragraph "
    "stating that the student may submit an appeal through the ProctorAI portal."
)

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False, undefined=StrictUndefined)
_client: anthropic.AsyncAnthropic | None = None


@dataclass(frozen=True)
class NoticeFacts:
    notice_reference: str
    student_name: str
    student_reg_no: str
    course_code: str
    room: str
    exam_date: str
    behaviours: list[str]
    penalty_type: str
    penalty_description: str
    issued_by: str


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=0,
            timeout=settings.anthropic_timeout_seconds,
        )
    return _client


def render_template_notice(facts: NoticeFacts) -> str:
    return _jinja_env.get_template(FALLBACK_TEMPLATE).render(**asdict(facts))


async def generate_notice(facts: NoticeFacts) -> tuple[str, NoticeSource]:
    if not settings.anthropic_api_key:
        return render_template_notice(facts), NoticeSource.TEMPLATE

    try:
        response = await _get_client().beta.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Case record:\n" + json.dumps(asdict(facts), indent=2)}],
            output_config={"effort": settings.anthropic_effort},
            betas=[REFUSAL_FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIConnectionError as exc:
        logger.error("notice generation failed (connection): %s", exc)
        return render_template_notice(facts), NoticeSource.TEMPLATE
    except anthropic.APIStatusError as exc:
        logger.error("notice generation failed status=%s request_id=%s", exc.status_code, exc.request_id)
        return render_template_notice(facts), NoticeSource.TEMPLATE

    if response.stop_reason in ("refusal", "max_tokens"):
        logger.warning("notice generation stopped early stop_reason=%s request_id=%s", response.stop_reason, response._request_id)
        return render_template_notice(facts), NoticeSource.TEMPLATE

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        return render_template_notice(facts), NoticeSource.TEMPLATE
    return text, NoticeSource.ANTHROPIC
