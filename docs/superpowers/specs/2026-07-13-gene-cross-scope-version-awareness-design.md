# Gene 跨 Scope 版本感知设计文档

**日期**：2026-07-13
**状态**：待批准

---

## 背景

Gene（技能）采用 personal / org_private / public 三向 fork 架构：`fork_gene_to_library()` 把一份技能内容复制成一条**完全独立**的新 DB 行，仅通过 `parent_gene_id` 记录"从哪 fork 来"的血缘，之后三份内容互不影响、互不同步。

用户反馈：覆盖个人库里的技能后，组织库/公共市场里由同一个技能 fork 出去的副本不会跟着更新，导致平台上出现"同名但内容版本不一致"的多份拷贝，用户无法感知。

**需求边界**（brainstorming 阶段已与用户确认，不在本次范围内的不要做）：

- 三份记录**仍然保持独立**，不做内容合并/自动同步——fork 出去的副本本来就允许被独立编辑，不能被别人的更新覆盖
- **不提供任何一键同步/推送更新的操作**，发现版本落后之后，具体怎么更新仍然走现有的手动覆盖/重新 fork 流程
- 只在**当前登录用户自己可见范围**内的血缘副本之间感知版本新旧（自己的 personal fork + 自己所在组织的 org fork + public），不做跨用户的全局血缘感知——例如 A 和 B 各自把同一个公共技能 fork 到自己的个人库，A 更新了自己的个人版本，不应该让 B 看到"有更新"的提示
- 不做内容 diff，只用时间戳判断"是否有更新的版本"，不展示具体改了什么

## 与既有设计的关系

仓库里已有一份**已批准但尚未实现**的设计 `docs/superpowers/specs/2026-07-01-skill-version-management-design.md`，管的是**同一个 scope 内**的版本升级链（`root_gene_id` + `previous_version_id`），并明确把"跨 fork 的版本继承"列为不在范围内。

与用户确认：本次设计**独立实现，不依赖也不合并**那份设计——两者是正交的概念（"同一 scope 内技能怎么升级版本" vs "同一技能在三个 scope 之间是否有人已经更新过"）。待 2026-07-01 那份设计真正落地时，需要再评估两者是否有整合空间（例如"覆盖时是否顺带产生新版本记录"），但不阻塞本次实现。

---

## 核心设计决策

### 用 `lineage_group_id` 分组，而非实时回溯 `parent_gene_id` 链

新增 `Gene.lineage_group_id` 字段，作为一个不透明的分组 key（不是外键，不要求指向一条现存活的行）。同一血缘下的 personal/org/public 副本共享同一个 `lineage_group_id`，查询"某技能的所有血缘副本"变成 `WHERE lineage_group_id = X`，可以在列表页批量查询（`WHERE lineage_group_id IN (...)`），避免逐条实时回溯 `parent_gene_id` 链带来的 N+1 查询。

### Fork lineage 与 Variant lineage 分离

`parent_gene_id` 目前被 `fork_gene_to_library()`（三向 fork）和 `publish_variant()` / `handle_creation_callback()`（AI 进化出的 variant）共用，语义混合。

`lineage_group_id` 只服务"三向 fork"这一个概念：

- Fork 出来的副本**继承**源的 `lineage_group_id`
- Variant 是进化出的新技能，语义上不是"同一个技能换了个 scope"，**不继承**父技能的 `lineage_group_id`，用自己的新 id 单独成组

---

## 数据模型

### Gene 表新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `lineage_group_id` | `String(36)`，索引，非 FK | 分组 key，同一血缘下的三向副本共享同一个值 |

不加唯一约束（同组允许多行），加普通索引支持 `WHERE lineage_group_id IN (...)` 批量查询。

### 传播规则（四条会产生 Gene 记录的路径）

| 路径 | `lineage_group_id` 取值 |
|---|---|
| `create_gene()` 全新创建（无冲突） | 自己的新 id（构造时 Python 端 `BaseModel.id` 已用 `default=lambda: str(uuid.uuid4())` 生成，构造对象时即可直接引用） |
| `create_gene()` overwrite 分支 | 继承被软删那一行的 `lineage_group_id`（在调用 `target.soft_delete()` 之前先读出 `target.lineage_group_id`，因为 soft_delete 只置 `deleted_at`，其余字段仍可读，但避免依赖时序，提前读取更清晰） |
| `fork_gene_to_library()` | 继承 `source.lineage_group_id` |
| `publish_variant()` / `handle_creation_callback()` | **不继承**，用自己的新 id 单独成组 |

`/admin/genes/{gene_id}` 就地编辑（`PUT`）不创建新行，`lineage_group_id` 不受影响，自然保留。

### Alembic 迁移

新增列先允许 `NULL`，迁移脚本内用 Python 端并查集（union-find）处理历史数据：

1. 取出所有 Gene 的 `(id, parent_gene_id)`
2. 沿 `parent_gene_id` 建无向连通分量（一条链无论朝哪个方向 fork 都会被分到同一组；variant 也会被历史数据误连进来——见下方"已知限制"）
3. 每个连通分量选一个稳定代表值作为该组的 `lineage_group_id`（用分量内最小的 `id` 字符串，保证确定性、可重复运行）
4. 孤立节点（无 `parent_gene_id` 且没有任何行以它为 `parent_gene_id`）各自成组，`lineage_group_id = 自己的 id`
5. 批量 `UPDATE`，完成后把列改为 `NOT NULL`

**已知限制**：由于当前 `parent_gene_id` 混用于 fork 和 variant 两种语义，历史数据回填时无法百分百区分"这条 parent_gene_id 链是三向 fork 还是 AI 进化出的 variant"——回填会保守地把两者都视为同一分量处理（历史数据里两者混在一起，无法事后精确拆分）。这只影响**回填那一刻已存在的历史行**；回填完成之后，新产生的数据严格按上表的传播规则处理，variant 和 fork 走向分离。回填前会跑一次统计（有多少历史行的 `parent_gene_id` 链同时包含 fork 产物和 variant 产物），如果数量很小可以接受，数量大再考虑单独处理。

---

## 版本落后检测

### 判定信号：`updated_at`

`Gene` 基类的 `updated_at` 在 `create_gene()` 覆盖（新建行）和 `/admin/genes/{id}` 就地编辑（`onupdate=func.now()`）两种更新路径下都会被正确刷新，统一用它判断"是否有更晚的版本"，不需要额外维护版本号或内容 hash。

### 判定逻辑

Gene G 判定为"落后"，当且仅当：存在一条与 G 同 `lineage_group_id`、未软删、且**对当前登录用户可见**的兄弟 S，满足 `S.updated_at > G.updated_at`。

"可见"复用现有权限模型：
- `visibility = public` → 任何登录用户可见
- `visibility = org_private` → 仅当前用户所在组织（`org_id` 匹配当前用户的组织成员关系）
- `visibility = personal` → 仅 `created_by = 当前用户 id`

### 批量查询（供列表页使用）

拿到一页 Gene 后：

1. 收集本页所有 `lineage_group_id`
2. 一次查询：`SELECT lineage_group_id, visibility, MAX(updated_at) FROM genes WHERE lineage_group_id IN (...) AND deleted_at IS NULL AND <可见性过滤> GROUP BY lineage_group_id, visibility`
3. 内存中按 `lineage_group_id` 聚合出"每个 scope 各自的最新 `updated_at`"
4. 逐条比较：某条 Gene 的 `newer_sibling_scopes` = 上述结果里，`updated_at` 比它新、且 `visibility` 不是它自己的那些 scope 列表

### API 输出

Gene 序列化字段（`_gene_to_dict`）新增只读字段：

```json
"newer_sibling_scopes": ["org_private", "public"]
```

值是 `personal` / `org_private` / `public` 的子集，空数组表示没有更晚的血缘副本。个人库、组织库、公共市场列表目前都走同一个 `list_genes()` → `_list_genes_local()` → `_gene_to_dict()` 路径，改一处即可覆盖三处列表。

前端拿到这个字段后按值拼文案（如"公共市场有更新版本"），本次不规定具体 UI 文案/组件实现细节，由前端按现有卡片角标样式风格实现（图标走 `lucide-vue-next`，不用 emoji）。

---

## 测试计划

- **传播规则**：`create_gene` 全新创建独立成组；`create_gene` overwrite 继承旧组（含"existing 为 None 只有 existing_name 命中"的分支，与近期修复的 overwrite bug 场景一致）；`fork_gene_to_library` 继承源组；`publish_variant` / `handle_creation_callback` 不继承、独立成组
- **落后检测**：三 scope 血缘齐全时，任一 scope 更新后其余两个正确标记；只有部分 scope 存在血缘副本时不误报；`personal` scope 的副本不会因为"同组但属于别的用户"的行而误判可见性
- **迁移回填**：构造链式（personal→org→public 单向 fork）、多分支（一条 public 被 fork 到两个不同 org）、孤立三种历史数据形状，验证并查集分组结果符合预期且迁移可重复运行（幂等）

## 不在本次范围内

- 任何自动或一键同步/推送更新的操作
- 跨用户的全局血缘感知（只看当前用户自己可见范围内的血缘副本）
- 内容 diff（只判断"是否更新"，不展示改了什么）
- 与 2026-07-01 版本管理设计的整合（该设计尚未落地，本次独立实现）

## 变更影响范围

| 层 | 文件 | 变更类型 |
|---|---|---|
| DB | `nodeskclaw-backend/app/models/gene.py` | 新增 `lineage_group_id` 字段 + 索引 |
| DB | `nodeskclaw-backend/alembic/versions/<new>.py` | 新增迁移（含并查集回填脚本） |
| Service | `nodeskclaw-backend/app/services/gene_service.py` | `create_gene` / `fork_gene_to_library` / `publish_variant` / `handle_creation_callback` 传播 `lineage_group_id`；新增落后检测批量查询；`_gene_to_dict` / `_list_genes_local` 接入 `newer_sibling_scopes` |
| Test | `nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py`（新建） | 传播规则 + 落后检测测试 |
| Test | 迁移脚本对应测试 | 并查集回填正确性 |
| 前端 | `nodeskclaw-portal/src/views/GeneMarket.vue` 等技能列表卡片 | 读取 `newer_sibling_scopes`，展示角标（具体 UI 落地时再定） |
