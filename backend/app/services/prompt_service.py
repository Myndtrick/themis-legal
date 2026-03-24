from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.prompt import PromptVersion

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

PROMPT_MANIFEST = {
    "LA-S1": {
        "file": "LA-S1-issue-classifier.txt",
        "desc": "Step 1 — Issue Classifier",
    },
    "LA-S2": {
        "file": "LA-S2-date-extractor.txt",
        "desc": "Step 2 — Date Extractor",
    },
    "LA-S3": {
        "file": "LA-S3-law-identifier.txt",
        "desc": "Step 3 — Law Identifier",
    },
    "LA-S5": {
        "file": "LA-S5-import-request.txt",
        "desc": "Step 5 — Import Request Generator",
    },
    "LA-S6": {
        "file": "LA-S6-article-selector.txt",
        "desc": "Step 6 — Article Selector",
    },
    "LA-S7": {
        "file": "LA-S7-answer-qa.txt",
        "desc": "Step 7 — Answer Generator (Mode 1 Q&A)",
    },
    "LA-S7-M2": {
        "file": "LA-S7-M2-answer-memo.txt",
        "desc": "Step 7 — Answer Generator (Mode 2 Memo)",
    },
    "LA-S7-M3": {
        "file": "LA-S7-M3-answer-comparison.txt",
        "desc": "Step 7 — Answer Generator (Mode 3 Comparison)",
    },
    "LA-S7-M4": {
        "file": "LA-S7-M4-answer-compliance.txt",
        "desc": "Step 7 — Answer Generator (Mode 4 Compliance)",
    },
    "LA-S7-M5": {
        "file": "LA-S7-M5-answer-checklist.txt",
        "desc": "Step 7 — Answer Generator (Mode 5 Checklist)",
    },
    "LA-CONF": {
        "file": "LA-CONF-confidence.txt",
        "desc": "Confidence Scorer",
    },
    "LA-CONFLICT": {
        "file": "LA-CONFLICT-conflict-resolver.txt",
        "desc": "Conflict Resolver",
    },
}


def seed_defaults(db: Session):
    """Insert default prompts if they don't exist yet."""
    seeded = 0
    for prompt_id, info in PROMPT_MANIFEST.items():
        existing = (
            db.query(PromptVersion)
            .filter(PromptVersion.prompt_id == prompt_id)
            .first()
        )
        if existing:
            continue

        filepath = PROMPTS_DIR / info["file"]
        if not filepath.exists():
            logger.warning(f"Prompt file not found: {filepath}")
            continue

        text = filepath.read_text(encoding="utf-8")
        version = PromptVersion(
            prompt_id=prompt_id,
            version_number=1,
            prompt_text=text,
            status="ACTIVE",
            created_by="system",
            modification_note="Initial default version",
        )
        db.add(version)
        seeded += 1

    db.commit()
    if seeded:
        logger.info(f"Seeded {seeded} default prompts")


def load_prompt(prompt_id: str, db: Session) -> tuple[str, int]:
    """Load the active prompt text. Returns (text, version_number)."""
    version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.status == "ACTIVE",
        )
        .order_by(PromptVersion.version_number.desc())
        .first()
    )
    if not version:
        raise ValueError(f"No active prompt found for {prompt_id}")
    return version.prompt_text, version.version_number


def get_all_active_prompts(db: Session) -> list[dict]:
    """Get summary of all prompts with their active version."""
    result = []
    for prompt_id, info in PROMPT_MANIFEST.items():
        version = (
            db.query(PromptVersion)
            .filter(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.status == "ACTIVE",
            )
            .order_by(PromptVersion.version_number.desc())
            .first()
        )
        result.append({
            "prompt_id": prompt_id,
            "description": info["desc"],
            "version_number": version.version_number if version else 0,
            "status": version.status if version else "missing",
            "modified_at": version.created_at.isoformat() if version else None,
        })
    return result
