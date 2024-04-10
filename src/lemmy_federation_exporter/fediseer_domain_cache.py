import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp.web

logger = logging.getLogger(__name__)


class FediseerDomainCache:
    _session: aiohttp.ClientSession
    _whitelist_params: dict[str, int | str]

    _domains: set[str]
    _last_updated: datetime | None = None
    _refresh_interval: int
    _update_task: asyncio.Task[Any] | None = None

    def __init__(
        self,
        *,
        user_agent: str,
        min_endorsements: int | None = None,
        min_guarantors: int | None = None,
        software_csv: str | None = None,
        return_limit: int | None = None,
        refresh_interval: int = 3600,
    ) -> None:
        self._session = aiohttp.ClientSession(
            headers={"user-agent": user_agent},
            timeout=aiohttp.ClientTimeout(total=10),
        )
        self._whitelist_params = {
            "domains": "true",
        }
        self._domains = set()
        if min_endorsements is not None:
            self._whitelist_params["endorsements"] = min_endorsements
        if min_guarantors is not None:
            self._whitelist_params["guarantors"] = min_guarantors
        if software_csv is not None:
            self._whitelist_params["software_csv"] = software_csv
        if return_limit is not None:
            self._whitelist_params["limit"] = return_limit
        self._refresh_interval = refresh_interval

    async def _update_verified_domains(self) -> None:
        logger.info("Refreshing Fediseer domain list")

        # Get first n verified instances with the required amount of endorsements and
        # guarantors
        # TODO: This does not implement pagination currently, so a maximum of 100
        # TODO: domains is supported. This is not also sorted by user counts or
        # TODO: guarantee/endorsement count, the API returns it by descending instance
        # TODO: creation date.
        async with self._session.get(
            "https://fediseer.com/api/v1/whitelist",
            params=self._whitelist_params,
        ) as r:
            r.raise_for_status()
            response: dict[str, list[str]] = await r.json()
            self._domains = {d.lower() for d in response["domains"]}
            logger.info("Refreshed Fediseer domain list")
            self._last_updated = datetime.now()

        self._update_task = None

    async def get_domains(self) -> set[str]:
        # Trigger background update if it's older than the refresh interval
        # and not already updating
        if (self._update_task is None or self._update_task.done()) and (
            self._last_updated is None
            or (datetime.now() - self._last_updated).seconds > self._refresh_interval
        ):
            self._update_task = asyncio.create_task(self._update_verified_domains())

        # Return stale data to avoid delays from fetching updated data
        # TODO: This should initially block until data was successfully
        # TODO: fetched for the first time
        return self._domains
