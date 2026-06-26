import logging

import httpx

from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)


def _parse_ragflow(resp: httpx.Response) -> dict:
    """校验 RAGFlow 响应并返回整个响应体（含 code/data/message）。

    RAGFlow 的错误约定很坑：dataset 不存在 / 无权访问时它**仍返回 HTTP 200**，
    错误体为 ``{"code": 非0, "message": "...", "data": false}``，成功才是
    ``{"code": 0, "data": {...}}``。若直接取 ``data`` 透传，``false`` 会撞上
    ``ApiResponse[dict]`` 的响应校验导致 500，且把 RAGFlow 的真实原因吞掉。
    统一在此把 message 透出，避免「验证通过、预览失败」却看不到原因。
    """
    if resp.status_code in (401, 403):
        raise BadRequestError(
            message="知识库服务鉴权失败，请检查 API Key",
            message_key="errors.kb.ragflow_auth_failed",
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise BadRequestError(
            message=f"知识库服务请求失败：HTTP {resp.status_code}",
            message_key="errors.kb.ragflow_error",
            message_params={"detail": f"HTTP {resp.status_code}"},
        ) from exc

    body = resp.json()
    code = body.get("code")
    if code not in (0, None):
        detail = body.get("message") or "未知错误"
        raise BadRequestError(
            message=f"知识库服务返回错误：{detail}",
            message_key="errors.kb.ragflow_error",
            message_params={"detail": detail},
        )
    return body


async def retrieve(
    endpoint: str,
    api_key: str,
    kb_id: str,
    question: str,
    top_k: int = 5,
) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{endpoint.rstrip('/')}/api/v1/retrieval",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"dataset_ids": [kb_id], "question": question, "top_k": top_k},
            )
        except httpx.HTTPError as exc:
            raise BadRequestError(
                message=f"无法连接知识库服务：{exc}",
                message_key="errors.kb.ragflow_unreachable",
            ) from exc

    body = _parse_ragflow(resp)
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    return data.get("chunks", [])


async def verify_connection(endpoint: str, api_key: str, kb_id: str | None = None) -> bool:
    """检测知识库连接是否可用。

    传入 ``kb_id`` 时，用与「预览文档」**完全相同**的接口校验该 dataset 是否真实可访问，
    确保「验证通过」即意味着预览/检索一定能成功，避免账号级连通性掩盖了 id 填错的问题。
    未传 ``kb_id`` 时退回账号级连通性检查。
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {api_key}"}
            if kb_id:
                resp = await client.get(
                    f"{endpoint.rstrip('/')}/api/v1/datasets/{kb_id}/documents",
                    headers=headers,
                    params={"page": 1, "page_size": 1},
                )
            else:
                resp = await client.get(
                    f"{endpoint.rstrip('/')}/api/v1/datasets",
                    headers=headers,
                )
            if resp.status_code != 200:
                return False
            return resp.json().get("code") in (0, None)
    except Exception:
        logger.debug("RAGFlow connection check failed", exc_info=True)
        return False


async def list_documents(
    endpoint: str,
    api_key: str,
    dataset_id: str,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    """获取 RAGFlow 数据集中的文档列表。

    成功返回 ``{"docs": [...], "total": N}``；RAGFlow 报错时由 ``_parse_ragflow``
    抛 ``BadRequestError`` 把真实原因（如「dataset 不存在」）透传给前端。
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                f"{endpoint.rstrip('/')}/api/v1/datasets/{dataset_id}/documents",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"page": page, "page_size": page_size},
            )
        except httpx.HTTPError as exc:
            raise BadRequestError(
                message=f"无法连接知识库服务：{exc}",
                message_key="errors.kb.ragflow_unreachable",
            ) from exc

    body = _parse_ragflow(resp)
    data = body.get("data")
    if not isinstance(data, dict):
        return {"docs": [], "total": 0}
    return data
