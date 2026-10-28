"""Background task dispatcher — OpenShift Jobs with in-process fallback."""

import json
import logging
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx

from reasons_service.config import settings  # noqa: F401 — used by in-process fallback

log = logging.getLogger(__name__)

_SA_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
_SA_CA_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
_SA_NS_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
_K8S_API = "https://kubernetes.default.svc"


def _is_openshift() -> bool:
    return _SA_TOKEN_PATH.exists()


def _k8s_namespace() -> str:
    if _SA_NS_PATH.exists():
        return _SA_NS_PATH.read_text().strip()
    return os.getenv("OPENSHIFT_NAMESPACE", "bthomass-dev")


def _k8s_headers() -> dict[str, str]:
    token = _SA_TOKEN_PATH.read_text().strip()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _k8s_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if _SA_CA_PATH.exists():
        ctx.load_verify_locations(str(_SA_CA_PATH))
    return ctx


async def dispatch_k8s_job(
    task_id: UUID,
    domain_id: UUID,
    task_type: str,
    config: dict,
) -> dict:
    ns = _k8s_namespace()
    job_name = f"task-{str(task_id)[:8]}"
    image = os.getenv("WORKER_IMAGE", "ghcr.io/benthomasson/reasons-service:latest")

    secrets_name = os.getenv("WORKER_SECRETS", "reasons-service-secrets")
    config_name = os.getenv("WORKER_CONFIG", "reasons-service-config")

    env_vars = [
        {"name": "TASK_ID", "value": str(task_id)},
        {"name": "DOMAIN_ID", "value": str(domain_id)},
        {"name": "TASK_TYPE", "value": task_type},
        {"name": "TASK_CONFIG", "value": json.dumps(config)},
        {"name": "REASONS_SERVICE_URL", "value": os.getenv("REASONS_SERVICE_URL", "http://reasons-service:8000")},
    ]

    job_manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": ns,
            "labels": {
                "app": "reasons-worker",
                "task-id": str(task_id)[:63],
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": 3600,
            "backoffLimit": 1,
            "template": {
                "metadata": {
                    "labels": {"app": "reasons-worker"},
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "worker",
                            "image": image,
                            "command": ["python", "-m", "reasons_service.worker"],
                            "envFrom": [
                                {"configMapRef": {"name": config_name}},
                                {"secretRef": {"name": secrets_name}},
                            ],
                            "env": env_vars,
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "256Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }

    url = f"{_K8S_API}/apis/batch/v1/namespaces/{ns}/jobs"

    try:
        async with httpx.AsyncClient(verify=_k8s_ssl_context()) as client:
            resp = await client.post(url, headers=_k8s_headers(), json=job_manifest, timeout=30)

        if resp.status_code in (200, 201):
            log.info("Dispatched K8s job %s for task %s", job_name, task_id)
            return {"job_name": job_name}
        else:
            error = resp.text[:500]
            log.error("K8s job dispatch failed (%d): %s", resp.status_code, error)
            return {"error": f"K8s dispatch failed ({resp.status_code}): {error}"}
    except Exception as e:
        log.error("K8s job dispatch error: %s", e)
        return {"error": str(e)}


async def dispatch_task(
    task_id: UUID,
    domain_id: UUID,
    task_type: str,
    config: dict,
) -> dict:
    if _is_openshift():
        return await dispatch_k8s_job(task_id, domain_id, task_type, config)

    # In-process fallback for local dev
    import asyncio
    from reasons_service.worker import run_task

    log.info("Running task %s in-process (no K8s available)", task_id)
    asyncio.create_task(run_task(str(task_id), str(domain_id), task_type, config))
    return {"mode": "in-process"}
