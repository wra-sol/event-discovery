#!/usr/bin/env python3
"""Provision or update the Railway cron service via GraphQL API."""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

GRAPHQL_URL = "https://backboard.railway.com/graphql/v2"

PROJECT_ID = "0a06a3ff-51b4-465b-934d-9b23fae6215f"
ENV_ID = "f32fb3d6-6a65-44b7-81da-f92027682f17"
APP_SERVICE_ID = "d43e6972-a057-4ce1-b7c1-ed81cc414886"
CRON_SERVICE_NAME = "cron"
APP_PUBLIC_URL = "https://app-production-00ec.up.railway.app"
REPO = "wra-sol/event-discovery"
BRANCH = "main"

CRON_VARS = {
    "EVENT_DISCOVERY_BASE_URL": APP_PUBLIC_URL,
    "EVENTS_CRAWL_API_TOKEN": "${{app.EVENTS_CRAWL_API_TOKEN}}",
    "DISCOVERY_ACCOUNT_ID": "1",
    "CRON_POLL_SECONDS": "5",
    "CRON_TIMEOUT_SECONDS": "900",
}


def token() -> str:
    config = json.loads(pathlib.Path.home().joinpath(".railway/config.json").read_text())
    return config["user"]["token"]


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
            "User-Agent": "event-discovery-setup/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def list_services() -> list[dict]:
    data = gql(
        """
        query project($id: String!) {
          project(id: $id) {
            services { edges { node { id name } } }
          }
        }
        """,
        {"id": PROJECT_ID},
    )
    return [e["node"] for e in data["project"]["services"]["edges"]]


def find_or_create_cron_service() -> str:
    for svc in list_services():
        if svc["name"] == CRON_SERVICE_NAME:
            print(f"Found existing cron service: {svc['id']}")
            return svc["id"]

    data = gql(
        """
        mutation serviceCreate($input: ServiceCreateInput!) {
          serviceCreate(input: $input) { id name }
        }
        """,
        {
            "input": {
                "projectId": PROJECT_ID,
                "name": CRON_SERVICE_NAME,
                "source": {"repo": REPO},
                "branch": BRANCH,
                "environmentId": ENV_ID,
            }
        },
    )
    service_id = data["serviceCreate"]["id"]
    print(f"Created cron service: {service_id}")
    return service_id


def configure_cron_instance(service_id: str) -> None:
    gql(
        """
        mutation serviceInstanceUpdate(
          $serviceId: String!
          $environmentId: String!
          $input: ServiceInstanceUpdateInput!
        ) {
          serviceInstanceUpdate(
            serviceId: $serviceId
            environmentId: $environmentId
            input: $input
          )
        }
        """,
        {
            "serviceId": service_id,
            "environmentId": ENV_ID,
            "input": {
                "startCommand": "python -m event_discovery cron-run",
                "cronSchedule": "0 13 * * 1-5",
                "builder": "RAILPACK",
                "railwayConfigFile": "/railway.cron.toml",
                "restartPolicyType": "NEVER",
            },
        },
    )
    print("Configured start command, cron schedule, and railway.cron.toml")


def upsert_variables(service_id: str, extra: dict[str, str] | None = None) -> None:
    variables = dict(CRON_VARS)
    if extra:
        variables.update(extra)
    for name, value in variables.items():
        gql(
            """
            mutation variableUpsert($input: VariableUpsertInput!) {
              variableUpsert(input: $input)
            }
            """,
            {
                "input": {
                    "projectId": PROJECT_ID,
                    "environmentId": ENV_ID,
                    "serviceId": service_id,
                    "name": name,
                    "value": value,
                }
            },
        )
        print(f"  set {name}")


def deploy(service_id: str) -> str:
    data = gql(
        """
        mutation deploy($serviceId: String!, $environmentId: String!) {
          serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId)
        }
        """,
        {"serviceId": service_id, "environmentId": ENV_ID},
    )
    deployment_id = data["serviceInstanceDeployV2"]
    print(f"Triggered deployment: {deployment_id}")
    return deployment_id


def main() -> int:
    brief_webhook = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    extra = {"BRIEF_WEBHOOK_URL": brief_webhook} if brief_webhook else {}

    try:
        service_id = find_or_create_cron_service()
        configure_cron_instance(service_id)
        print("Setting environment variables:")
        upsert_variables(service_id, extra)
        deploy(service_id)
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("\nCron service ready.")
    print(f"  service id: {service_id}")
    print(f"  schedule:   0 13 * * 1-5 UTC (weekday 8:00 EST)")
    print("\nConfigure webhook destinations per account in the web UI:")
    print("  Sites → Daily brief webhooks")
    if brief_webhook:
        print("\nLegacy BRIEF_WEBHOOK_URL env fallback was set on the cron service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
