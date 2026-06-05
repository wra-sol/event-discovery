from __future__ import annotations

import logging
import os
import sys

from .automation_client import AutomationClientError, fetch_automation_delivery, run_remote_daily_automation
from .automation_delivery_settings import AutomationDeliverySettings
from .brief_delivery import build_failure_payload, build_webhook_payload, deliver_brief_webhook

log = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "EVENT_DISCOVERY_BASE_URL",
    "EVENTS_CRAWL_API_TOKEN",
    "DISCOVERY_ACCOUNT_ID",
)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _parse_account_id() -> int | None:
    raw = _env("DISCOVERY_ACCOUNT_ID") or _env("EVENT_DISCOVERY_ACCOUNT_ID")
    if raw.isdigit():
        return int(raw)
    return None


def _parse_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _missing_required_env() -> list[str]:
    missing: list[str] = []
    for name in _REQUIRED_ENV:
        if name == "DISCOVERY_ACCOUNT_ID":
            if _parse_account_id() is None:
                missing.append(name)
        elif not _env(name):
            missing.append(name)
    return missing


def _resolve_delivery_settings(
    base_url: str,
    *,
    token: str,
    account_id: int,
) -> AutomationDeliverySettings:
    delivery = fetch_automation_delivery(base_url, token=token, account_id=account_id)
    legacy_url = _env("BRIEF_WEBHOOK_URL")
    if legacy_url:
        from .automation_delivery_settings import WebhookDestination

        delivery.webhooks.append(
            WebhookDestination(
                id="env-fallback",
                url=legacy_url,
                label="Environment fallback",
                enabled=True,
            )
        )
    return delivery


def _try_deliver_failure(webhook_urls: list[str], error: str) -> None:
    if not webhook_urls:
        return
    payload = build_failure_payload(error)
    for url in webhook_urls:
        try:
            deliver_brief_webhook(url, payload)
        except Exception as e:
            log.warning("Failed to post failure webhook to %s: %s", url[:48], e)


def _deliver_brief_to_webhooks(
    webhook_urls: list[str],
    payload: dict,
) -> bool:
    if not webhook_urls:
        return True
    ok = True
    for url in webhook_urls:
        try:
            deliver_brief_webhook(url, payload)
            log.info("Delivered brief webhook to %s", url[:48])
        except Exception as e:
            log.error("Webhook delivery failed for %s: %s", url[:48], e)
            ok = False
    return ok


def main_cron_run() -> int:
    """
    One-shot Railway cron entry: remote full crawl, fetch daily brief, POST to configured webhooks.
    Webhook destinations are loaded from the account's /api/automation/delivery settings.
    """
    missing = _missing_required_env()
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        return 2

    base_url = _env("EVENT_DISCOVERY_BASE_URL").rstrip("/")
    token = _env("EVENTS_CRAWL_API_TOKEN")
    account_id = _parse_account_id()
    assert account_id is not None
    brief_format = _env("BRIEF_FORMAT") or "markdown"
    poll_seconds = _parse_float("CRON_POLL_SECONDS", 5.0)
    timeout_seconds = _parse_float("CRON_TIMEOUT_SECONDS", 900.0)
    env_skip_if_empty = _parse_bool("CRON_SKIP_WEBHOOK_IF_EMPTY", False)

    try:
        delivery = _resolve_delivery_settings(base_url, token=token, account_id=account_id)
    except AutomationClientError as e:
        log.error("Could not load automation delivery settings: %s", e)
        return 1

    webhook_urls = delivery.enabled_webhook_urls()
    skip_if_empty = delivery.skip_if_empty or env_skip_if_empty

    try:
        brief = run_remote_daily_automation(
            base_url,
            token=token,
            account_id=account_id,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
    except AutomationClientError as e:
        log.error("Remote automation failed: %s", e)
        _try_deliver_failure(webhook_urls, str(e))
        return 1

    if not webhook_urls:
        log.info(
            "Crawl succeeded (job_id=%s); no webhook destinations configured for account %s",
            brief.crawl_job.job_id if brief.crawl_job else None,
            account_id,
        )
        return 0

    brief_dict = brief.to_dict()
    if skip_if_empty and brief.pending_count == 0:
        log.info(
            "Crawl succeeded (job_id=%s); pending_count=0 — skipping webhook delivery",
            brief.crawl_job.job_id if brief.crawl_job else None,
        )
        return 0

    payload = build_webhook_payload(brief_dict, fmt=brief_format)
    if not _deliver_brief_to_webhooks(webhook_urls, payload):
        return 1

    job_id = brief.crawl_job.job_id if brief.crawl_job else None
    log.info(
        "Cron run complete: pending_count=%s crawl_job_id=%s delivered_to=%s webhook(s)",
        brief.pending_count,
        job_id,
        len(webhook_urls),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if argv:
        log.warning("cron-run ignores CLI arguments")
    return main_cron_run()


if __name__ == "__main__":
    sys.exit(main())
