from datetime import datetime
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectBase(BaseModel):
    """Base project schema with common attributes."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique name or title of the project",
    )
    source_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Source provider or mechanism (e.g. 'github', 'gitlab', 'local')",
    )
    source_url: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional repository or clone URL",
    )
    status: str = Field(
        default="pending",
        min_length=1,
        max_length=50,
        description="Current project processing status",
    )

    @field_validator("name", "source_type", "status", mode="before")
    @classmethod
    def validate_non_blank_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                raise ValueError("String value cannot be blank or whitespace-only")
            return v_stripped
        return v


class ProjectCreate(ProjectBase):
    """Payload schema for creating a new project."""
    pass


class ProjectUpdate(BaseModel):
    """Payload schema for partial project update (PATCH)."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated project name",
    )
    source_type: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Updated project source type",
    )
    source_url: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Updated source URL or None to clear",
    )
    status: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Updated project status",
    )

    @field_validator("name", "source_type", "status", mode="before")
    @classmethod
    def validate_not_none_and_not_blank(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null")
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                raise ValueError("String value cannot be blank or whitespace-only")
            return v_stripped
        return v

    @field_validator("source_url", mode="before")
    @classmethod
    def validate_source_url(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v_stripped = v.strip()
            return v_stripped if v_stripped else None
        return v


class ProjectResponse(BaseModel):
    """Public representation of a Project."""

    id: uuid.UUID
    name: str
    source_type: str
    source_url: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
