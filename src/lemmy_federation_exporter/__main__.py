import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import NotRequired, TypedDict

import aiohttp.web
from prometheus_client.core import GaugeMetricFamily, Timestamp

from .fediseer_domain_cache import FediseerDomainCache
from .prom_util import CollectorHelper

USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT",
    "Lemmy-Federation-Exporter (+https://github.com/Nothing4You/lemmy-federation-exporter)",
)

FILTER_FEDISEER_ENABLED = os.environ.get("FILTER_FEDISEER_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)

# Setup sharable aiohttp data
fediseer_domain_cache = aiohttp.web.AppKey("fediseer_domain_cache", FediseerDomainCache)

logger = logging.getLogger(__name__)


# TODO: This should probably be split a bit to improve readability.
# TOOD: Afterwards the noqa marker for C901 and PLR0915 can be removed.
async def metrics(request: aiohttp.web.Request) -> aiohttp.web.Response:  # noqa: C901, PLR0915
    # Get request query paramaters
    instance = request.query.getone("instance")
    remote_instances_filter_str: str | None = request.query.get("remote_instances")
    remote_instances_filter = (
        remote_instances_filter_str.lower().split(",")
        if remote_instances_filter_str is not None
        else None
    )
    c = CollectorHelper()

    # last_retry = Last send try

    label_keys = (
        "remote_instance",
        "remote_software",
    )

    instance_last_seen_metric = GaugeMetricFamily(
        "lemmy_federation_state_instance_last_seen",
        "Timestamp instance was last seen",
        labels=label_keys,
    )
    c.add_metric(instance_last_seen_metric)
    instance_last_seen_metric_since_seconds = GaugeMetricFamily(
        "lemmy_federation_state_instance_last_seen_since_seconds",
        "Seconds since instance was last seen",
        labels=label_keys,
    )
    c.add_metric(instance_last_seen_metric_since_seconds)
    failure_count_metric = GaugeMetricFamily(
        "lemmy_federation_state_failure_count",
        "Failure count of last send",
        labels=label_keys,
    )
    c.add_metric(failure_count_metric)
    last_successful_id_metric = GaugeMetricFamily(
        "lemmy_federation_state_last_successful_id",
        "Last successfully sent activity id",
        labels=label_keys,
    )
    c.add_metric(last_successful_id_metric)
    last_successful_id_local_metric = GaugeMetricFamily(
        "lemmy_federation_state_last_successful_id_local",
        "Highest last successfully sent activity id across all linked instances",
    )
    c.add_metric(last_successful_id_local_metric)
    activities_behind_metric = GaugeMetricFamily(
        "lemmy_federation_state_activities_behind",
        "Distance between highest activity id and last successfully sent activity id",
        labels=label_keys,
    )
    c.add_metric(activities_behind_metric)
    last_successful_published_time_metric = GaugeMetricFamily(
        "lemmy_federation_state_last_successful_published_time",
        "Timestamp of last successfully sent activity",
        labels=label_keys,
    )
    c.add_metric(last_successful_published_time_metric)
    last_successful_published_since_seconds_metric = GaugeMetricFamily(
        "lemmy_federation_state_last_successful_published_since_seconds",
        "Seconds since last successfully sent activity",
        labels=label_keys,
    )
    c.add_metric(last_successful_published_since_seconds_metric)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as cs:
        r = await cs.get(
            f"https://{instance}/api/v3/federated_instances",
            headers={"user-agent": USER_AGENT},
        )
        r.raise_for_status()
        j = await r.json()

    now = datetime.now(UTC)
    cutoff_unseen_instances = now - timedelta(days=2)
    unix_epoch = datetime(1970, 1, 1, tzinfo=UTC)
    unix_now = now - unix_epoch
    prom_ts = Timestamp(unix_now.total_seconds(), unix_now.microseconds * 1000)

    # for instances using an allowlist, the same dicts are present in allowlist
    # if allowlist is empty, any linked instance is considered
    if len(j["federated_instances"]["allowed"]) > 0:
        federation_type = "allowed"
    else:
        federation_type = "linked"

    max_id = max(
        i.get("federation_state", {}).get("last_successful_id", 0)
        for i in j["federated_instances"][federation_type]
    )

    # Access the shared fediseer domain cache
    if FILTER_FEDISEER_ENABLED:
        fediseer_domains = await request.app[fediseer_domain_cache].get_domains()
    else:
        fediseer_domains = set()

    for i in j["federated_instances"][federation_type]:
        remote_instance = i["domain"].strip().lower()

        # If the domain filter is passed as query
        # parameter and the domain is not included, skip the domain.
        #
        # This replaces the fediseer filter if it's set.
        if remote_instances_filter is not None:
            if remote_instance not in remote_instances_filter:
                continue

        # If the domain is not in the list of verified domains, skip the domain
        elif FILTER_FEDISEER_ENABLED and remote_instance not in fediseer_domains:
            continue

        if "updated" not in i:
            logger.debug("[%s] missing updated for %s", instance, i["domain"])
            continue
        last_seen = datetime.fromisoformat(i["updated"])
        if last_seen < cutoff_unseen_instances:
            continue

        if "federation_state" not in i:
            logger.debug("[%s] missing federation_state for %s", instance, i["domain"])
            continue

        labels = (
            i["domain"],
            i.get("software", ""),
        )
        instance_last_seen_metric.add_metric(
            labels,
            (last_seen - unix_epoch).total_seconds(),
            prom_ts,
        )
        instance_last_seen_metric_since_seconds.add_metric(
            labels,
            (now - last_seen).total_seconds(),
            prom_ts,
        )
        failure_count_metric.add_metric(
            labels,
            i["federation_state"]["fail_count"],
            prom_ts,
        )
        last_successful_id_metric.add_metric(
            labels,
            i["federation_state"]["last_successful_id"],
            prom_ts,
        )
        activities_behind_metric.add_metric(
            labels,
            max_id - i["federation_state"]["last_successful_id"],
            prom_ts,
        )
        if "last_successful_published_time" in i["federation_state"]:
            last_successful_published_time_metric.add_metric(
                labels,
                (
                    datetime.fromisoformat(
                        i["federation_state"]["last_successful_published_time"],
                    )
                    - unix_epoch
                ).total_seconds(),
                prom_ts,
            )
            last_successful_published_since_seconds_metric.add_metric(
                labels,
                (
                    now
                    - datetime.fromisoformat(
                        i["federation_state"]["last_successful_published_time"],
                    )
                ).total_seconds(),
                prom_ts,
            )

    last_successful_id_local_metric.add_metric((), max_id, prom_ts)

    metrics_result = c.generate().decode()
    return aiohttp.web.Response(text=metrics_result)


async def init_filter_fediseer(app: aiohttp.web.Application) -> None:
    class KwArgs(TypedDict):
        min_endorsements: NotRequired[int]
        min_guarantors: NotRequired[int]
        software_csv: NotRequired[str]
        return_limit: NotRequired[int]
        refresh_interval: NotRequired[int]

    env_types = {
        "min_endorsements": int,
        "min_guarantors": int,
        "software_csv": str,
        "return_limit": int,
        "refresh_interval": int,
    }

    kwargs: KwArgs = {}

    for k, t in env_types.items():
        env_key = f"FILTER_FEDISEER_{k}".upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if t is int:
                try:
                    # TODO: Figure out if this can be dealt with properly without
                    # TODO: skipping type checking
                    kwargs[k] = int(env_val)  # type: ignore[literal-required]
                except ValueError:
                    logger.warning(
                        "Unable to parse %s=%r as number, ignoring...",
                        env_key,
                        env_val,
                    )
            else:
                # TODO: Figure out if this can be dealt with properly without
                # TODO: skipping type checking
                kwargs[k] = env_val  # type: ignore[literal-required]

    app[fediseer_domain_cache] = FediseerDomainCache(
        user_agent=USER_AGENT,
        **kwargs,
    )

    # This ensures the task doesn't get discarded during execution but discards
    # the reference once completed.
    # Based on https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
    background_tasks = set()
    task = asyncio.create_task(app[fediseer_domain_cache].get_domains())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def init() -> aiohttp.web.Application:
    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO").upper(),
        format="%(asctime)s - %(levelname)8s - %(name)s:%(funcName)s - %(message)s",
    )

    logging.Formatter.formatTime = (  # type: ignore[method-assign]
        lambda self, record, datefmt: datetime.fromtimestamp(record.created, UTC)  # type: ignore[assignment,misc] # noqa: ARG005
        .astimezone()
        .isoformat()
    )

    app = aiohttp.web.Application()

    if FILTER_FEDISEER_ENABLED:
        await init_filter_fediseer(app)

    app.add_routes(
        [
            aiohttp.web.get("/metrics", metrics),
        ],
    )

    return app


if __name__ == "__main__":
    aiohttp.web.run_app(init())
