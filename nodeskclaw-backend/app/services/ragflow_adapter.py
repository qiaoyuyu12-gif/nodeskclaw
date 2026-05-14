import logging

import httpx

logger = logging.getLogger(__name__)


async def retrieve(
    endpoint: str,
    api_key: str,
    kb_id: str,
    question: str,
    top_k: int = 5,
) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{endpoint.rstrip('/')}/api/v1/retrieval",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"dataset_ids": [kb_id], "question": question, "top_k": top_k},
        )
        resp.raise_for_status()
        return resp.json()["data"]["chunks"]


async def verify_connection(endpoint: str, api_key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{endpoint.rstrip('/')}/api/v1/datasets",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return resp.status_code == 200
    except Exception:
        logger.debug("RAGFlow connection check failed", exc_info=True)
        return False
