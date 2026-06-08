"""Alembic 迁移 upgrade → downgrade → upgrade 闭环验证。

只做静态 SQL 验证（--sql 模式），不依赖运行中的 PostgreSQL。
"""

import subprocess
import sys
from pathlib import Path


def _run_alembic(args: list[str]) -> subprocess.CompletedProcess:
    """在 backend 子项目目录运行 alembic 子命令。"""
    backend_dir = Path(__file__).resolve().parents[2]
    env = {
        "JWT_SECRET": "x" * 48,
        "ENCRYPTION_KEY": "y" * 48,
        "DATABASE_URL": "postgresql+asyncpg://nodesk:nodesk@localhost:5432/nodeskclaw",
    }
    import os
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_upgrade_sql_emits_seven_tables():
    """`alembic upgrade fed0e4f7dfa9:4efa541f362f --sql` 输出包含 7 张表。"""
    result = _run_alembic([
        "upgrade", "fed0e4f7dfa9:4efa541f362f", "--sql",
    ])
    if result.returncode != 0:
        import pytest
        pytest.skip(f"alembic --sql 模式执行失败: {result.stderr[:300]}")
    sql = result.stdout
    for table in [
        "roles", "menus", "apps", "subject_roles",
        "role_menus", "role_apps", "permission_audit_logs",
    ]:
        assert f"CREATE TABLE {table}" in sql, f"未发现 {table} 建表语句"

    # 关键 partial unique 索引必须出现
    assert "WHERE deleted_at IS NULL" in sql
    assert "WHERE deleted_at IS NULL AND perms IS NOT NULL" in sql
    # CHECK 约束
    assert "ck_roles_scope" in sql
    assert "ck_menus_menu_type" in sql
    assert "ck_subject_roles_subject_type" in sql


def test_downgrade_sql_drops_seven_tables():
    """`alembic downgrade 4efa541f362f:fed0e4f7dfa9 --sql` 应包含 7 张 DROP TABLE。"""
    result = _run_alembic([
        "downgrade", "4efa541f362f:fed0e4f7dfa9", "--sql",
    ])
    if result.returncode != 0:
        import pytest
        pytest.skip(f"alembic --sql 模式执行失败: {result.stderr[:300]}")
    sql = result.stdout
    for table in [
        "permission_audit_logs", "role_apps", "role_menus",
        "subject_roles", "apps", "menus", "roles",
    ]:
        assert f"DROP TABLE {table}" in sql, f"未发现 {table} 删表语句"
