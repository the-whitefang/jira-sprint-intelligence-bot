"""Sprint and Employee Metrics caching.

Provides high-level cache interfaces for sprint analytics and workload data.
TTLs are calibrated to how fast each specific metric tends to change.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.analytics.sprint_analytics import IssueCounts, SprintAnalyticsResult
from app.analytics.workload_analytics import EmployeeWorkload, WorkloadAnalyticsResult
from app.integrations.jira.schemas import JiraSprint
from app.shared.cache_repository import CacheRepository


class SprintCache:
    """Cache manager for sprint-level data.
    
    Instead of extending CacheRepository directly, this class acts as a facade
    over multiple CacheRepository instances, since it manages multiple distinct
    Pydantic models (Sprint, IssueCounts, Workload, etc.) all under the
    'sprint' namespace.
    """
    
    def __init__(self, client: Redis) -> None:
        self._sprint_repo = CacheRepository(client, "sprint", JiraSprint)
        self._counts_repo = CacheRepository(client, "sprint", IssueCounts)
        self._analytics_repo = CacheRepository(client, "sprint", SprintAnalyticsResult)
        self._workload_repo = CacheRepository(client, "sprint", WorkloadAnalyticsResult)
        self._client = client

    async def get_current_sprint(self, board_id: int) -> JiraSprint | None:
        return await self._sprint_repo.get(f"current:{board_id}")

    async def set_current_sprint(self, board_id: int, sprint: JiraSprint) -> None:
        # Current sprint changes rarely, but we want to catch sprint start/end
        # within a reasonable time.
        await self._sprint_repo.set(f"current:{board_id}", sprint, ttl_seconds=300)

    async def get_issue_counts(self, sprint_id: int) -> IssueCounts | None:
        return await self._counts_repo.get(f"counts:{sprint_id}")

    async def set_issue_counts(self, sprint_id: int, counts: IssueCounts) -> None:
        # Issue counts change very frequently (tickets moving, closing).
        await self._counts_repo.set(f"counts:{sprint_id}", counts, ttl_seconds=60)

    async def get_velocity(self, sprint_id: int) -> SprintAnalyticsResult | None:
        return await self._analytics_repo.get(f"velocity:{sprint_id}")

    async def set_velocity(self, sprint_id: int, result: SprintAnalyticsResult) -> None:
        # Velocity and burn rate change moderately during a sprint.
        await self._analytics_repo.set(f"velocity:{sprint_id}", result, ttl_seconds=900)

    async def get_workload(self, sprint_id: int) -> WorkloadAnalyticsResult | None:
        return await self._workload_repo.get(f"workload:{sprint_id}")

    async def set_workload(self, sprint_id: int, result: WorkloadAnalyticsResult) -> None:
        # Workload (time spent/remaining) changes frequently.
        await self._workload_repo.set(f"workload:{sprint_id}", result, ttl_seconds=120)

    async def invalidate_sprint(self, sprint_id: int) -> None:
        """Invalidate all cached metrics for a specific sprint."""
        await self._counts_repo.delete(f"counts:{sprint_id}")
        await self._analytics_repo.delete(f"velocity:{sprint_id}")
        await self._workload_repo.delete(f"workload:{sprint_id}")

    async def invalidate_current_sprint(self, board_id: int) -> None:
        """Invalidate the pointer to the current sprint for a board."""
        await self._sprint_repo.delete(f"current:{board_id}")


class EmployeeMetricsCache(CacheRepository[EmployeeWorkload]):
    """Cache manager for individual employee workload and metrics."""
    
    def __init__(self, client: Redis) -> None:
        super().__init__(client, "employee", EmployeeWorkload)

    async def get_metrics(self, account_id: str, sprint_id: int | None = None) -> EmployeeWorkload | None:
        suffix = f"sprint:{sprint_id}:member:{account_id}" if sprint_id else f"all_time:member:{account_id}"
        return await self.get(suffix)

    async def set_metrics(self, account_id: str, metrics: EmployeeWorkload, sprint_id: int | None = None) -> None:
        suffix = f"sprint:{sprint_id}:member:{account_id}" if sprint_id else f"all_time:member:{account_id}"
        await self.set(suffix, metrics, ttl_seconds=300)
