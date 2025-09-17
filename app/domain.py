from __future__ import annotations
import enum


class Status(enum.StrEnum):
    saved = "saved"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
