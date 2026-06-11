"""PlanBasedQuotaChecker — EE 基于套餐的配额检查。

部署前校验：
1. 实例数量是否超限
2. CPU/内存/存储是否超组织总配额
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import Instance, InstanceStatus
from ee.backend.models.plan import Plan
from app.services.quota.checker import QuotaChecker


class PlanBasedQuotaChecker(QuotaChecker):
    """基于 Organization.plan 对应的 Plan 进行配额限制。"""

    async def check_deploy_quota(
        self,
        org: Any,
        db: AsyncSession,
        *,
        cpu_request: str = "0",
        mem_request: str = "0",
        storage_size: str = "0",
    ) -> None:
        from app.core.exceptions import BadRequestError

        # 1. 查找组织的套餐
        plan_result = await db.execute(
            select(Plan).where(Plan.name == org.plan, Plan.is_active.is_(True))
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            # 套餐不存在或未激活，默认允许（兼容无套餐情况）
            logger.warning("组织 %s 的套餐 %s 不存在或未激活，跳过配额检查", org.id, org.plan)
            return

        # 2. 统计当前实例数量
        active_instances_result = await db.execute(
            select(func.count(Instance.id)).where(
                Instance.org_id == org.id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
        current_instance_count = active_instances_result.scalar_one()

        if current_instance_count >= plan.max_instances:
            raise BadRequestError(
                message=f"实例数量超限：当前 {current_instance_count} 个，最多 {plan.max_instances} 个（套餐: {plan.display_name}）",
                message_key="errors.quota.instance_limit_exceeded",
            )

        # 3. 统计当前资源使用
        used_result = await db.execute(
            select(
                func.coalesce(func.sum(Instance.cpu_limit), 0),
                func.coalesce(func.sum(Instance.mem_limit), 0),
                func.coalesce(func.sum(Instance.storage_size), 0),
            ).where(
                Instance.org_id == org.id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
        used_cpu, used_mem, used_storage = used_result.one()

        # 解析请求资源
        req_cpu = self._parse_cpu(cpu_request)
        req_mem = self._parse_mem(mem_request)
        req_storage = self._parse_storage(storage_size)

        # 获取当前配额限制
        total_cpu = self._parse_cpu(plan.max_total_cpu)
        total_mem = self._parse_mem(plan.max_total_mem)
        total_storage = self._parse_storage(plan.max_total_storage)

        if (used_cpu + req_cpu) > total_cpu:
            raise BadRequestError(
                message=f"CPU 超限：当前使用 {used_cpu}核，请求 +{req_cpu}核，限额 {total_cpu}核",
                message_key="errors.quota.cpu_limit_exceeded",
            )

        if (used_mem + req_mem) > total_mem:
            raise BadRequestError(
                message=f"内存超限：当前使用 {used_mem}Gi，请求 +{req_mem}Gi，限额 {total_mem}Gi",
                message_key="errors.quota.memory_limit_exceeded",
            )

        if (used_storage + req_storage) > total_storage:
            raise BadRequestError(
                message=f"存储超限：当前使用 {used_storage}Gi，请求 +{req_storage}Gi，限额 {total_storage}Gi",
                message_key="errors.quota.storage_limit_exceeded",
            )

    def _parse_cpu(self, value: str) -> float:
        """解析 CPU 字符串为核数（浮点数）。"""
        if not value:
            return 0.0
        value = value.strip()
        if value.isdigit():
            return float(value)
        # 支持 "2" -> 2, "500m" -> 0.5
        if value.endswith("m"):
            return float(value[:-1]) / 1000
        return float(value)

    def _parse_mem(self, value: str) -> float:
        """解析内存字符串为 GiB（浮点数）。"""
        if not value:
            return 0.0
        value = value.strip()
        if value.endswith("Gi"):
            return float(value[:-2])
        if value.endswith("Mi"):
            return float(value[:-2]) / 1024
        if value.endswith("G"):
            return float(value[:-1])
        if value.endswith("M"):
            return float(value[:-1]) / 1024
        return float(value)

    def _parse_storage(self, value: str) -> float:
        """解析存储字符串为 GiB（浮点数）。"""
        return self._parse_mem(value)  # 存储同样用 Gi 单位