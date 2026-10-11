"""Validated request models shared by the API routers."""

from typing import Literal

from pydantic import BaseModel, Field


class SubjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#10B981", pattern=r"^#[0-9a-fA-F]{6}$")


class StartSessionInput(BaseModel):
    subject_id: int | None = None
    kind: Literal["focus", "break"] = "focus"
