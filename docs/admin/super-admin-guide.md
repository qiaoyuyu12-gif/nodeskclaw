# 超管后台操作手册

> 适用范围：EE 版部署超管角色。位置：`/admin`。

## 入口

- 仅 `is_super_admin=true` 用户可见 `/admin` 入口。
- CE 版本不提供本手册涉及的功能。

## 组织管理

- `/admin/orgs` — 组织列表，支持创建 / 编辑 / 软删
- 行点击进入 `/admin/orgs/:id` 查看 Overview / 成员 / 功能开关
- 删除前必须先停止组织下的所有运行中实例

## 用户管理

- `/admin/users` — 全局用户搜索（按 email/name），分页
- 行点击进入 `/admin/users/:id`
- 禁用 / 启用：二次确认；不能停用自己
- 撤销超管：不能撤销自己；不能撤销最后一个超管
- 重置密码：弹窗显示临时密码 + 复制按钮；用户下次登录强制改密；明文不入审计

## 功能开关（Feature Override）

- `/admin/features` — 列表显示 features.yaml 全集 + 各自被覆盖的组织数
- 点击某 feature → 右侧抽屉显示该 feature 上的所有 override（分页）
- 反向入口：组织详情页 Features tab 以组织为主轴查看 / 切换
- 强制开 / 强制关：写入 reason 留待审计追溯
- 恢复默认：删除 override，回落 edition_features 默认

## 审计日志

- `/admin/audit` — 时间倒序
- 筛选：actor_id / action（来自 enum）/ 时间区间
- 行展开看 before/after JSON
- 保留期 90 天；超期物理删除（job 每天 03:00 运行）

## 安全约定

- 临时密码仅一次性返回，关闭弹窗后无再查口令
- 登录成功 / 失败 / 登出全部入审计
- 失败 actor 写 `anonymous`，details.attempted_email 用于排查爆破
- 数据删除一律软删 + 级联白名单（详见设计文档 §4.3）
