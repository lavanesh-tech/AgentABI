"""Persistence access for GitHubWebhookDelivery (Security Phase E spec
§8/§10). Used by `GitHubWebhookService` to detect duplicate deliveries
across API instances/restarts — never a process-local cache."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github_webhook_delivery import GitHubWebhookDelivery


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_delivery_id(self, delivery_id: str) -> GitHubWebhookDelivery | None:
        stmt = select(GitHubWebhookDelivery).where(GitHubWebhookDelivery.delivery_id == delivery_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def add(self, delivery: GitHubWebhookDelivery) -> None:
        self._session.add(delivery)
