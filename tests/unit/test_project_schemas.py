from datetime import datetime, timezone
import uuid
import pytest
from pydantic import ValidationError

from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate


def test_project_create_valid():
    """Verify valid ProjectCreate payload parsing and defaults."""
    payload = {
        "name": "MindMesh Engine",
        "source_type": "github",
    }
    data = ProjectCreate(**payload)
    assert data.name == "MindMesh Engine"
    assert data.source_type == "github"
    assert data.source_url is None
    assert data.status == "pending"


def test_project_create_custom_fields():
    """Verify ProjectCreate with explicit source_url and status."""
    payload = {
        "name": "Core Service",
        "source_type": "gitlab",
        "source_url": "https://gitlab.com/org/repo",
        "status": "ready",
    }
    data = ProjectCreate(**payload)
    assert data.name == "Core Service"
    assert data.source_type == "gitlab"
    assert data.source_url == "https://gitlab.com/org/repo"
    assert data.status == "ready"


@pytest.mark.parametrize("blank_name", ["", "   ", "\t\n"])
def test_project_create_rejects_blank_name(blank_name):
    """Verify ProjectCreate rejects empty or whitespace-only name."""
    with pytest.raises(ValidationError):
        ProjectCreate(name=blank_name, source_type="github")


def test_project_create_name_max_length():
    """Verify ProjectCreate rejects names exceeding 255 characters."""
    with pytest.raises(ValidationError):
        ProjectCreate(name="a" * 256, source_type="github")


@pytest.mark.parametrize("blank_source_type", ["", "   "])
def test_project_create_rejects_blank_source_type(blank_source_type):
    """Verify ProjectCreate rejects empty or whitespace-only source_type."""
    with pytest.raises(ValidationError):
        ProjectCreate(name="Valid Name", source_type=blank_source_type)


def test_project_create_source_type_max_length():
    """Verify ProjectCreate rejects source_type exceeding 50 characters."""
    with pytest.raises(ValidationError):
        ProjectCreate(name="Valid Name", source_type="s" * 51)


def test_project_create_source_url_max_length():
    """Verify ProjectCreate rejects source_url exceeding 1024 characters."""
    with pytest.raises(ValidationError):
        ProjectCreate(name="Valid", source_type="github", source_url="https://" + "u" * 1020)


def test_project_update_omitted_fields():
    """Verify ProjectUpdate treats omitted fields as unset."""
    update = ProjectUpdate()
    dump = update.model_dump(exclude_unset=True)
    assert dump == {}


def test_project_update_partial_fields():
    """Verify ProjectUpdate handles partial field updates."""
    update = ProjectUpdate(name="Updated Title")
    dump = update.model_dump(exclude_unset=True)
    assert dump == {"name": "Updated Title"}


def test_project_update_clear_source_url():
    """Verify ProjectUpdate allows explicitly clearing source_url with None."""
    update = ProjectUpdate(source_url=None)
    dump = update.model_dump(exclude_unset=True)
    assert "source_url" in dump
    assert dump["source_url"] is None


@pytest.mark.parametrize("field_name", ["name", "source_type", "status"])
def test_project_update_rejects_none_for_required_attributes(field_name):
    """Verify ProjectUpdate rejects None for non-nullable fields."""
    with pytest.raises(ValidationError):
        ProjectUpdate(**{field_name: None})


@pytest.mark.parametrize("field_name", ["name", "source_type", "status"])
def test_project_update_rejects_blank_strings(field_name):
    """Verify ProjectUpdate rejects blank strings for non-nullable fields."""
    with pytest.raises(ValidationError):
        ProjectUpdate(**{field_name: "   "})


def test_project_response_serialization():
    """Verify ProjectResponse schema validates and serializes correctly."""
    now = datetime.now(timezone.utc)
    proj_id = uuid.uuid4()
    data = {
        "id": proj_id,
        "name": "MindMesh Test",
        "source_type": "local",
        "source_url": "/tmp/repo",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    resp = ProjectResponse.model_validate(data)
    assert resp.id == proj_id
    assert resp.name == "MindMesh Test"
    assert resp.source_url == "/tmp/repo"


def test_pagination_params_valid():
    """Verify default and custom PaginationParams."""
    p_default = PaginationParams()
    assert p_default.limit == 20
    assert p_default.offset == 0

    p_custom = PaginationParams(limit=50, offset=10)
    assert p_custom.limit == 50
    assert p_custom.offset == 10


def test_pagination_params_bounds():
    """Verify PaginationParams boundary enforcement."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=0)

    with pytest.raises(ValidationError):
        PaginationParams(limit=101)

    with pytest.raises(ValidationError):
        PaginationParams(offset=-1)


def test_paginated_response():
    """Verify PaginatedResponse envelope format."""
    now = datetime.now(timezone.utc)
    proj = ProjectResponse(
        id=uuid.uuid4(),
        name="Test",
        source_type="github",
        source_url=None,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    paginated = PaginatedResponse[ProjectResponse](
        items=[proj],
        total=1,
        limit=10,
        offset=0,
    )
    assert len(paginated.items) == 1
    assert paginated.total == 1
    assert paginated.limit == 10
    assert paginated.offset == 0
