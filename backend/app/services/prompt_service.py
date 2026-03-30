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
    "LA-S5": {
        "file": "LA-S5-import-request.txt",
        "desc": "Step 5 — Import Request Generator",
    },
    "LA-S6": {
        "file": "LA-S6-article-selector.txt",
        "desc": "Step 6 — Article Selector",
    },
    "LA-S6.5": {
        "file": "LA-S6.5-relevance-check.txt",
        "desc": "Step 6.5 — Relevance Checker",
    },
    "LA-S6.8": {
        "file": "LA-S6.8-legal-reasoning.txt",
        "desc": "Step 6.8 — Legal Reasoning (RL-RAP)",
    },
    "LA-S7-template": {
        "file": "LA-S7-answer-template.txt",
        "desc": "Step 7 — Answer Generator (Shared Template)",
    },
    "LA-S7-mode-simple": {
        "file": "LA-S7-mode-simple.txt",
        "desc": "Step 7 — Mode: Simple Q&A",
    },
    "LA-S7-mode-qa": {
        "file": "LA-S7-mode-qa.txt",
        "desc": "Step 7 — Mode: Full Q&A",
    },
    "LA-S7-mode-memo": {
        "file": "LA-S7-mode-memo.txt",
        "desc": "Step 7 — Mode: Legal Memo",
    },
    "LA-S7-mode-comparison": {
        "file": "LA-S7-mode-comparison.txt",
        "desc": "Step 7 — Mode: Version Comparison",
    },
    "LA-S7-mode-compliance": {
        "file": "LA-S7-mode-compliance.txt",
        "desc": "Step 7 — Mode: Compliance Check",
    },
    "LA-S7-mode-checklist": {
        "file": "LA-S7-mode-checklist.txt",
        "desc": "Step 7 — Mode: Legal Checklist",
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


def sync_prompts_from_files(db: Session):
    """Update DB prompts from files when the file content differs from the active DB version.

    Creates a new version (deactivating the old one) for any prompt whose file
    has changed since the last sync.
    """
    updated = 0
    for prompt_id, info in PROMPT_MANIFEST.items():
        filepath = PROMPTS_DIR / info["file"]
        if not filepath.exists():
            continue

        file_text = filepath.read_text(encoding="utf-8")

        # Get current active version
        active = (
            db.query(PromptVersion)
            .filter(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.status == "ACTIVE",
            )
            .order_by(PromptVersion.version_number.desc())
            .first()
        )

        if not active:
            continue

        # Compare — skip if identical
        if active.prompt_text.strip() == file_text.strip():
            continue

        # Deactivate old version
        active.status = "INACTIVE"

        # Create new version
        new_version = PromptVersion(
            prompt_id=prompt_id,
            version_number=active.version_number + 1,
            prompt_text=file_text,
            status="ACTIVE",
            created_by="system",
            modification_note="Synced from file",
        )
        db.add(new_version)
        updated += 1

    db.commit()
    if updated:
        logger.info(f"Synced {updated} prompts from files")


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
