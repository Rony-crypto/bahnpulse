"""Paths and settings shared by all scripts."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW_S1 = DATA / "raw" / "s1"
RAW_S3 = DATA / "raw" / "s3"
CONFIG = ROOT / "config"
DOCS = ROOT / "docs"

load_dotenv(ROOT / ".env")


def env(name: str, required: bool = True) -> str:
    """Read an environment variable; fail with a clear message if a required one is missing."""
    value = os.getenv(name, "").strip()
    if required and not value:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value
