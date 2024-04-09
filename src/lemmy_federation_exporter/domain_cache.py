import os
from datetime import datetime

import aiohttp.web

class DomainCache:
    HTTP_USER_AGENT: str     
    FILTER_VERIFIED_DOMAINS: str
    FILTER_VERIFIED_ENDORSEMENTS: int
    FILTER_VERIFIED_GUARANTORS: int
    FILTER_VERIFIED_RETURN_LIMIT: int
    
    domains: list[str]
    user_agent: str
    last_updated: datetime

    @classmethod
    async def create(cls):
        cls.HTTP_USER_AGENT                = os.getenv("HTTP_USER_AGENT",                   "Lemmy-Federation-Exporter (+https://github.com/Nothing4You/lemmy-federation-exporter)")
        cls.FILTER_VERIFIED_DOMAINS        = os.getenv("FILTER_VERIFIED_DOMAINS",           "false")
        cls.FILTER_VERIFIED_ENDORSEMENTS   = int(os.getenv("FILTER_VERIFIED_ENDORSEMENTS",  2))
        cls.FILTER_VERIFIED_GUARANTORS     = int(os.getenv("FILTER_VERIFIED_GUARANTORS",    1))
        cls.FILTER_VERIFIED_RETURN_LIMIT   = int(os.getenv("FILTER_VERIFIED_RETURN_LIMIT ", 100))

        cls.domains = await cls.update_verified_domains()

        return cls

    @classmethod
    async def update_verified_domains(self) -> list[str]:
        # Get top 100 verified instances that have 2 endorsements and 1 gaurantor
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as cs:
            r = await cs.get(
                "https://fediseer.com/api/v1/whitelist",
                headers={"user-agent": self.HTTP_USER_AGENT},
                params={
                    "endorsements": self.FILTER_VERIFIED_ENDORSEMENTS,
                    "guarantors": self.FILTER_VERIFIED_ENDORSEMENTS,
                    "software_csv": "lemmy",
                    "limit": self.FILTER_VERIFIED_RETURN_LIMIT,
                    "domains": "true",
                },
            )
            r.raise_for_status()
            response = await r.json()
            self.last_updated = datetime.now()
            return response["domains"]
    
    @classmethod
    async def get_domains(self) -> list[str]:
        # Update verified domain cache if its been longer than 10 minutes
        if (datetime.now() - self.last_updated).seconds > 600:
            await self.update_verified_domains()
        return self.domains
    