from typing import Generic, List, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for paginated requests."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items to return (1-100)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip (>= 0)",
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic envelope for paginated collections."""

    items: List[T] = Field(description="List of paginated items")
    total: int = Field(ge=0, description="Total count of items across all pages")
    limit: int = Field(ge=1, description="Limit applied to this page")
    offset: int = Field(ge=0, description="Offset applied to this page")
