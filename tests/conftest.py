import asyncio
import sys
from typing import AsyncGenerator
import uuid
from httpx import ASGITransport, AsyncClient, Response
import pytest
from sqlalchemy import delete

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.session import async_session_factory
from app.main import app
from app.models.project import Project


class IsolatedAsyncClient(AsyncClient):
    """Test HTTP client that tracks project IDs created during its session."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.created_project_ids: set[uuid.UUID] = set()

    def track_project_id(self, project_id: uuid.UUID | str) -> None:
        try:
            if isinstance(project_id, str):
                self.created_project_ids.add(uuid.UUID(project_id))
            else:
                self.created_project_ids.add(project_id)
        except Exception:
            pass

    async def request(self, method: str, url, *args, **kwargs) -> Response:
        response = await super().request(method, url, *args, **kwargs)
        if response.status_code == 201 and "/api/v1/projects" in str(url):
            try:
                data = response.json()
                if isinstance(data, dict) and "id" in data:
                    self.track_project_id(data["id"])
            except Exception:
                pass
        return response


@pytest.fixture
async def async_client() -> AsyncGenerator[IsolatedAsyncClient, None]:
    """Test HTTP client with automatic database isolation and teardown cleanup.

    Tracks projects created via this specific client instance and cleans up only
    those projects upon teardown. This guarantees test isolation without deleting
    unrelated projects, even under concurrent test runs.
    """
    transport = ASGITransport(app=app)
    async with IsolatedAsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            if client.created_project_ids:
                try:
                    async with async_session_factory() as session:
                        async with session.begin():
                            await session.execute(
                                delete(Project).where(Project.id.in_(client.created_project_ids))
                            )
                except Exception:
                    pass
