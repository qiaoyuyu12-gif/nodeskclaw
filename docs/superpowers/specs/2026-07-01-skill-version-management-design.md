# Skill 版本管理设计文档

**日期**：2026-07-01  
**状态**：已批准，待实现

---

## 背景

Gene 模型已有 `version`、`parent_gene_id`、`InstanceGene.installed_version` 字段，骨架存在但不完整：

- 无 API 支持查询某 Skill 的历史版本列表
- `parent_gene_id` 同时承载 fork lineage 和 version lineage，语义混用
- 实例绑定只存 `installed_version` 字符串，无法 pin 到特定 Gene record

---

## 核心设计决策

### Fork vs Version 分离

`parent_gene_id` 只用于 fork lineage（personal/org/public 三向 fork），不参与版本管理。

版本链使用独立字段：

```
root_gene_id         -- 指向该 Skill 的第一个版本（自身是 root 时为 NULL）
previous_version_id  -- 指向上一个版本（第一版为 NULL）
```

两字段各司其职：
- `root_gene_id`：O(1) 索引聚合某 Skill 全量版本
- `previous_version_id`：精确版本前驱关系，用于 diff 和回滚链路

---

## 数据模型

### Gene 表新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `root_gene_id` | FK → Gene.id, nullable | 为 NULL 表示自身是 root 版本 |
| `previous_version_id` | FK → Gene.id, nullable | 第一版无前驱 |
| `version_changelog` | TEXT, nullable | 本版本更新说明 |

版本链示例：
```
Gene v1.0.0  root_gene_id=NULL,    previous_version_id=NULL
Gene v1.0.1  root_gene_id=v1.id,   previous_version_id=v1.id
Gene v1.1.0  root_gene_id=v1.id,   previous_version_id=v1.0.1.id
```

索引：`root_gene_id` 加索引（版本列表查询依赖）。

### InstanceGene 表新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `pinned_gene_version_id` | FK → Gene.id, nullable | pin 到的历史版本 |
| `pin_mode` | ENUM('auto','pinned'), default='auto' | auto=跟随最新；pinned=锁定 |

**语义**：
- `pin_mode='auto'`：`pinned_gene_version_id=NULL`，可升级到最新版
- `pin_mode='pinned'`：`pinned_gene_version_id` 指向特定 Gene record，轻量回滚时只更新此字段，不触发重装

### Alembic 迁移

单张迁移文件，添加上述 5 个字段及对应索引，禁止手写 revision ID。

---

## API 设计

### 1. 版本历史查询

```
GET /genes/{gene_id}/versions
```

响应：
```json
[
  {
    "id": "...",
    "version": "1.0.0",
    "version_changelog": "初始版本",
    "created_at": "2026-01-01T00:00:00Z",
    "is_latest": false
  },
  {
    "id": "...",
    "version": "1.1.0",
    "version_changelog": "优化输出格式",
    "created_at": "2026-06-01T00:00:00Z",
    "is_latest": true
  }
]
```

实现：`WHERE root_gene_id = resolve_root(gene_id) ORDER BY created_at ASC`

`resolve_root`：若 `gene.root_gene_id IS NULL` 则 `root = gene.id`，否则 `root = gene.root_gene_id`。

### 2. 发布新版本（独立端点）

```
POST /genes/{gene_id}/versions
Body: {
  "version": "1.2.0",
  "version_changelog": "...",
  // 其他 gene 字段（名称、manifest 等）
}
```

服务层逻辑：
1. 验证 `version` > 当前最新版本（语义化版本比较）
2. 创建新 Gene record，`root_gene_id = resolve_root(gene_id)`，`previous_version_id = gene_id`
3. 返回新 Gene 信息

### 3. 上传/手动创建自动识别新版本

`POST /genes/upload-folder` 和 `POST /genes/manual`：

- 若检测到同 `slug` + 同 `scope`（visibility + org_id/created_by）的 Gene 已存在
- 且上传的 `version` > 现有最新版本
- → 自动走"发布新版本"逻辑，填写 `root_gene_id` / `previous_version_id`
- 否则走现有创建逻辑

### 4. 实例版本 Pin 管理

```
PUT /instances/{instance_id}/genes/{gene_id}/pin
Body: {
  "pin_mode": "auto" | "pinned",
  "pinned_gene_version_id": "..." | null
}
```

- 轻量操作，只更新 InstanceGene 字段，不触发 uninstall/reinstall
- `pin_mode='auto'` 时 `pinned_gene_version_id` 强制置 NULL

### 5. 安装时指定版本

```
POST /instances/{instance_id}/genes/install
Body: {
  "gene_slug": "...",
  "pin_mode": "auto" | "pinned",        // 新增，默认 auto
  "pinned_gene_version_id": "..." | null // 新增，pinned 时必填
}
```

安装弹窗提供选择，后端兼容原有调用（字段可选）。

---

## 前端设计

### InstanceGenes.vue — Skill 卡片改动

- 新增版本 badge：显示 `installed_version`（如 `v1.0.1`）
- 新增锁图标：`pin_mode='pinned'` 显示锁图标，`auto` 显示解锁图标，点击切换
- 点击版本 badge → 打开 `VersionHistoryDrawer`

### VersionHistoryDrawer.vue（新组件）

时间线展示版本历史：
- 每行：版本号、changelog、发布时间
- 每行操作按钮：**回滚到此版本**（调 `PUT .../pin`，pin 到该版本）
- 顶部切换：跟随最新版 / 锁定当前版
- 当前 pinned 版本高亮显示

### GeneMarketDialog.vue / 安装弹窗改动

- 新增"版本"下拉选择（默认最新版，调 `GET /genes/{id}/versions` 填充）
- 新增"锁定版本"开关（默认关 = auto）
- 选择非最新版时自动切换为 pinned 模式

---

## 不在本次范围内

- 版本 diff 展示（manifest 内容对比）
- 自动升级通知/推送
- 版本删除/废弃（软删除逻辑复杂，延后）
- 跨 fork 的版本继承

---

## 变更影响范围

| 层 | 文件 | 变更类型 |
|----|------|---------|
| DB | `nodeskclaw-backend/app/models/gene.py` | 新增 5 个字段 |
| DB | `alembic/versions/xxx.py` | 新增迁移文件 |
| Schema | `nodeskclaw-backend/app/schemas/gene.py` | 新增字段 |
| Service | `nodeskclaw-backend/app/services/gene_service.py` | 新增版本创建/查询/pin 逻辑 |
| API | `nodeskclaw-backend/app/api/genes.py` | 新增 3 个端点 |
| 前端 Store | `nodeskclaw-portal/src/stores/gene.ts` | 新增字段和 API 方法 |
| 前端组件 | `nodeskclaw-portal/src/views/InstanceGenes.vue` | 改动卡片 |
| 前端组件 | `nodeskclaw-portal/src/components/VersionHistoryDrawer.vue` | 新增组件 |
| 前端组件 | `nodeskclaw-portal/src/components/GeneMarketDialog.vue` | 改动安装弹窗 |
