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
- 只在**当前登录用户自己可见范围**内的血缘副本之间感知版本新旧（自己的 personal fork + 自己所在**所有**组织各自的 org fork + public），不做跨用户的全局血缘感知——例如 A 和 B 各自把同一个公共技能 fork 到自己的个人库，A 更新了自己的个人版本，不应该让 B 看到"有更新"的提示；若用户同时是多个组织成员且这些组织各自独立 fork 了同一血缘，按具体组织分开展示，不合并成一个笼统的"组织库"结论，组织之间也不互相评判谁的版本更权威
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

### 用 `content_updated_at` 而非 `updated_at` 判断"内容是否更新"

最初设想直接用 `Gene` 基类自带的 `updated_at` 做新旧判断，验证下来有两个问题：

1. **fork 瞬间会产生假阳性**：fork 出来的新副本 `created_at`/`updated_at` 必然晚于源头，但内容在 fork 那一刻是完全相同的拷贝——如果直接比较，刚 fork 完就会误报"源头有更新版本"。
2. **`updated_at` 被大量内容无关的字段变更污染**：`updated_at` 配了 `onupdate=func.now()`，而 `install_count`（每次安装 +1）、`avg_rating`（每次评分）、`effectiveness_score`（效果分重算）都是对同一行的原地 `UPDATE`，跟 skill 内容本身毫无关系，却都会顺带把 `updated_at` 刷新，导致角标被大量噪音触发。

因此新增专门字段 `Gene.content_updated_at`，只在内容真正变化时才更新，不设 `onupdate`（避免被无关字段变更自动带动）：

**注意"更新"判断的粒度**：`content_updated_at` 只区分"是否发生过一次 `create_gene()` 插入新行的动作"（overwrite、或下方"软删记录血缘回接"命中），不做内容级别的字节对比。也就是说，哪怕重新上传的内容跟删除前一模一样，也会被当成一次新版本、刷新 `content_updated_at`，从而让其余 scope 显示"有更新"。这是有意的简化，不引入 manifest/description 的内容 hash 比对，与"不做内容 diff"的既定范围保持一致。

| 路径 | `content_updated_at` 取值 |
|---|---|
| `create_gene()` 全新创建 / overwrite 插入新行 | 插入时间（`server_default=func.now()`，与 `created_at` 语义一致） |
| `fork_gene_to_library()` | **继承 `source.content_updated_at`，不重置为当前时间**——内容是原样拷贝，不算"更新" |
| `publish_variant()` / `handle_creation_callback()` | 插入时间（不继承，本来就单独成组） |
| `/admin/genes/{gene_id}` 就地编辑（`update_gene`） | 仅当本次请求实际修改了内容字段（`name`/`description`/`short_description`/`category`/`tags`/`icon`/`version`/`manifest` 任意一个）时，显式置为当前时间；只改 `is_featured`/`is_published` 不触发 |
| `rate_gene` / 安装计数 / 效果分重算等其他原地 UPDATE | 不触碰 `content_updated_at` |

---

## 数据模型

### Gene 表新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `lineage_group_id` | `String(36)`，索引，非 FK | 分组 key，同一血缘下的三向副本共享同一个值 |
| `content_updated_at` | `DateTime(timezone=True)`，`server_default=func.now()`，无 `onupdate` | 内容最后一次真正变化的时间，用于版本落后判定 |

`lineage_group_id` 不加唯一约束（同组允许多行），加普通索引支持 `WHERE lineage_group_id IN (...)` 批量查询。

### 传播规则（四条会产生 Gene 记录的路径）

| 路径 | `lineage_group_id` 取值 | `content_updated_at` 取值 |
|---|---|---|
| `create_gene()` 全新创建，且同 scope 内**没有**任何软删记录匹配 slug/name | 自己的新 id（构造时 Python 端 `BaseModel.id` 已用 `default=lambda: str(uuid.uuid4())` 生成，构造对象时即可直接引用） | 插入时间（server_default） |
| `create_gene()` 全新创建，但同 scope 内**有**软删记录匹配 slug/name（先删除、再重新上传同名技能） | 回接：继承那条软删记录的 `lineage_group_id`（见下方"软删记录的血缘回接"） | 插入时间（server_default，视为一次新内容） |
| `create_gene()` overwrite 分支 | 继承被软删那一行的 `lineage_group_id`（在调用 `target.soft_delete()` 之前先读出 `target.lineage_group_id`，因为 soft_delete 只置 `deleted_at`，其余字段仍可读，但避免依赖时序，提前读取更清晰） | 插入时间（server_default，新行=新内容） |
| `fork_gene_to_library()` | 继承 `source.lineage_group_id` | 继承 `source.content_updated_at` |
| `publish_variant()` / `handle_creation_callback()` | **不继承**，用自己的新 id 单独成组 | 插入时间（server_default） |

`/admin/genes/{gene_id}` 就地编辑（`PUT`）不创建新行，`lineage_group_id` 不受影响；`content_updated_at` 按上一节的规则条件更新。

### 软删记录的血缘回接

背景：`create_gene()` 的判重查询（`get_gene_by_slug_in_scope` / `get_gene_by_name_in_scope`）只看未软删的行。用户如果先手动删除个人库里的技能、再重新上传同名技能（两个独立动作，不是走 `overwrite=True`），判重查询找不到任何活跃冲突，会落入"全新创建"分支——如果不做特殊处理，这次重传会生成一个全新的 `lineage_group_id`，跟原来组织库/公共市场那份的血缘彻底断开，即使内容完全一样也不会再被识别为"同一个技能"。

修复：`create_gene()` 全新创建分支在生成新 `lineage_group_id` 之前，多一步检查——在同一 scope 内（`visibility` + `org_id`/`created_by` 一致）按 slug 查一条**软删**的记录（`deleted_at IS NOT NULL`），查不到再按 name 查；找到则继承它的 `lineage_group_id`；如果同时按 slug、按 name 各查到了不同的软删记录，取 `deleted_at` 更晚（最近一次删除）的那条；都查不到才生成全新的 `lineage_group_id`。

已知局限：这是一个基于 slug/name 匹配的启发式，无法区分"删除后重传的是同一个技能"和"纯属巧合，删掉一个技能后又传了个碰巧同名的全新技能"——两种情况在数据层面无法可靠区分，本设计选择偏向"倾向于认为是同一个技能"（与用户的直觉更符合：大多数"先删再传"的场景确实是想替换/恢复同一个技能）。

### Alembic 迁移

两个新列先允许 `NULL`，迁移脚本内处理历史数据：

1. `lineage_group_id`：Python 端并查集（union-find）——取出所有 Gene 的 `(id, parent_gene_id)`，沿 `parent_gene_id` 建无向连通分量（一条链无论朝哪个方向 fork 都会被分到同一组；variant 也会被历史数据误连进来——见下方"已知限制"），每个连通分量选一个稳定代表值作为该组的 `lineage_group_id`（用分量内最小的 `id` 字符串，保证确定性、可重复运行），孤立节点各自成组
2. `content_updated_at`：历史行没有真实的"内容最后变化时间"可考据，回填为 `created_at`（该行本身的创建时间，是唯一确定可信的下界；这只影响回填那一刻已存在的历史行，之后所有变更严格按上表规则维护，不影响新产生的数据）
3. 批量 `UPDATE`，完成后把两列都改为 `NOT NULL`

**已知限制**：由于当前 `parent_gene_id` 混用于 fork 和 variant 两种语义，历史数据回填时无法百分百区分"这条 parent_gene_id 链是三向 fork 还是 AI 进化出的 variant"——回填会保守地把两者都视为同一分量处理（历史数据里两者混在一起，无法事后精确拆分）。这只影响**回填那一刻已存在的历史行**；回填完成之后，新产生的数据严格按上表的传播规则处理，variant 和 fork 走向分离。回填前会跑一次统计（有多少历史行的 `parent_gene_id` 链同时包含 fork 产物和 variant 产物），如果数量很小可以接受，数量大再考虑单独处理。

---

## 版本落后检测

### 判定信号：`content_updated_at`（不是 `updated_at`，理由见上方"用 content_updated_at 而非 updated_at"）

### 判定逻辑

Gene G 判定为"落后"，当且仅当：存在一条与 G 同 `lineage_group_id`、未软删、且**对当前登录用户可见**的兄弟 S，满足 `S.content_updated_at > G.content_updated_at`。

"可见"复用现有权限模型：
- `visibility = public` → 任何登录用户可见
- `visibility = org_private` → 仅当前用户所在组织（`org_id` 匹配当前用户的组织成员关系）
- `visibility = personal` → 仅 `created_by = 当前用户 id`

**分组粒度是 `(visibility, org_id)` 而不是只有 `visibility`**：同一个技能可能在用户所在的多个组织里各自被独立 fork（比如用户同时是 A、B 两个组织成员，A、B 各自 fork 了同一个公共技能并分别修改），这种情况下不能把 A、B 两个组织的副本合并成一个"org_private"笼统结论——查看 A 组织的副本时，要能区分"是 B 组织有更新"还是"是公共市场有更新"，分别标出组织名，而不是笼统说"组织库有更新"。`personal` 天然只有当前用户一份，`public` 天然全局一份，只有 `org_private` 需要按 `org_id` 再拆一层。

### 批量查询（供列表页使用）

拿到一页 Gene 后：

1. 收集本页所有 `lineage_group_id`
2. 一次查询：`SELECT lineage_group_id, visibility, org_id, MAX(content_updated_at) FROM genes WHERE lineage_group_id IN (...) AND deleted_at IS NULL AND <可见性过滤> GROUP BY lineage_group_id, visibility, org_id`（`org_private` 的可见性过滤限定在当前用户所在的组织 id 集合内，即使用户在多个组织，也只会聚合出用户实际有权限看到的那几个组织的副本）
3. 若结果里出现 `org_private` 分组，批量查一次涉及到的 `org_id` 对应的组织名（`Organization` 表），用于展示
4. 内存中按 `lineage_group_id` 聚合出"每个 (visibility, org_id) 组合各自最新的 `content_updated_at`"
5. 逐条比较：某条 Gene 的落后列表 = 上述结果里，`content_updated_at` 比它新、且 `(visibility, org_id)` 不是它自己的那些条目

### API 输出

Gene 序列化字段（`_gene_to_dict`）新增只读字段 `newer_sibling_versions`（结构化数组，按具体组织区分，而不是笼统的 scope 类型字符串）：

```json
"newer_sibling_versions": [
  {"visibility": "personal", "org_id": null, "org_name": null, "content_updated_at": "2026-07-12T10:00:00Z"},
  {"visibility": "org_private", "org_id": "org-a-id", "org_name": "研发部", "content_updated_at": "2026-07-13T08:00:00Z"},
  {"visibility": "org_private", "org_id": "org-b-id", "org_name": "市场部", "content_updated_at": "2026-07-11T09:00:00Z"},
  {"visibility": "public", "org_id": null, "org_name": null, "content_updated_at": "2026-07-10T12:00:00Z"}
]
```

空数组表示没有更晚的血缘副本。个人库、组织库、公共市场列表目前都走同一个 `list_genes()` → `_list_genes_local()` → `_gene_to_dict()` 路径，改一处即可覆盖三处列表。

前端拿到这个字段后按 `visibility`/`org_name` 拼文案（如"研发部有更新版本"、"公共市场有更新版本"，同一 Gene 可能同时对应多条），本次不规定具体 UI 文案/组件实现细节，由前端按现有卡片角标样式风格实现（图标走 `lucide-vue-next`，不用 emoji）。

### 场景验证

用户提出的场景：A 上传技能到个人库 → fork 到组织 X → 组织 X 的另一个成员 B 把这份技能 fork 到自己的个人库并修改后重新上传。

- A 的个人副本、组织 X 副本：`content_updated_at` 都是 A 上传那一刻的值（fork 到组织 X 时继承，没人改过内容）——A 无论看自己的个人库还是组织 X 库，两边一致，**无提示**
- B 修改后新建的个人副本：`content_updated_at` 刷新为 B 修改的时间，但这一行 `visibility=personal, created_by=B`，只在 B 自己的可见范围内——A 看不到这一行，不受影响
- B 自己查看组织 X 的副本时，B 可见范围内包含"自己的个人库"（比组织 X 新）——B 会看到"个人库有更新"提示，符合预期

---

## 测试计划

- **传播规则**：`create_gene` 全新创建（同 scope 无任何软删匹配）独立成组、`content_updated_at` = 插入时间；`create_gene` overwrite 继承旧组、`content_updated_at` 刷新为插入时间（含"existing 为 None 只有 existing_name 命中"的分支，与近期修复的 overwrite bug 场景一致）；`fork_gene_to_library` 继承源组**且继承 `content_updated_at`（不重置）**；`publish_variant` / `handle_creation_callback` 不继承、独立成组
- **软删记录血缘回接**：删除个人库技能后，重新上传同 slug/同 name 的技能，新行应继承旧（软删）行的 `lineage_group_id`，与组织库/公共市场的血缘关系保持不变；同时按 slug、name 分别匹配到不同软删行时，取 `deleted_at` 更晚的那条；同 scope 内确实没有任何软删匹配时才生成全新 `lineage_group_id`（验证不会误接一个毫不相关、只是巧合同名的历史技能之外的场景——本用例只覆盖"能找到匹配就接上"这一半，"巧合同名"的假阳性是已知局限，不强求测试覆盖）
- **fork 不产生假阳性**：fork 完成的瞬间，新副本与源头的 `content_updated_at` 相同，`newer_sibling_versions` 应为空（覆盖用户描述的场景，验证"刚 fork 完不会误报"）
- **`update_gene` 按字段选择性刷新**：只改 `is_featured`/`is_published` 不刷新 `content_updated_at`；改 `name`/`manifest` 等内容字段才刷新
- **`content_updated_at` 不受无关字段污染**：`rate_gene`、`install_gene`（`install_count += 1`）、效果分重算等操作后，`content_updated_at` 保持不变
- **落后检测**：三 scope 血缘齐全时，任一 scope 更新后其余两个正确标记；只有部分 scope 存在血缘副本时不误报；`personal` scope 的副本不会因为"同组但属于别的用户"的行而误判可见性；**同一血缘在用户所在的多个组织里各自独立 fork** 时，`newer_sibling_versions` 按 `org_id` 分开列出各自的 `content_updated_at`，用户不是成员的组织的副本即使同血缘也不出现在结果里
- **迁移回填**：构造链式（personal→org→public 单向 fork）、多分支（一条 public 被 fork 到两个不同 org）、孤立三种历史数据形状，验证并查集分组结果符合预期且迁移可重复运行（幂等）；`content_updated_at` 回填为各行 `created_at`

## 不在本次范围内

- 任何自动或一键同步/推送更新的操作
- 跨用户的全局血缘感知（只看当前用户自己可见范围内的血缘副本）
- 内容 diff（只判断"是否更新"，不展示改了什么）
- 与 2026-07-01 版本管理设计的整合（该设计尚未落地，本次独立实现）
- 组织与组织之间的"谁该以谁为准"仲裁——多个组织各自独立 fork 后各自演化是允许的正常状态，本设计只负责告知"存在更新的血缘副本"，不评判哪个版本更权威
- 已安装到实例上的技能与源 Gene 的更新同步/引用修复——`create_gene()` overwrite 是"软删旧行 + 插入新 id 新行"，已安装该技能的实例上 `InstanceGene.gene_id` 仍指向被软删的旧行，导致 `get_instance_genes()` 等函数把已安装技能"丢"掉。这是一个独立的、本次改动之前就存在的 bug，用户已确认按 Task #12 单独跟进，不在本设计范围内处理
- 实例已装技能感知源 Gene 更新——本设计的"落后检测"只覆盖个人库/组织库/公共市场三方之间的库内对比，不覆盖"已经装到 AI 员工实例上的技能，相对当初安装来源是否已经过时"。这依赖 Task #12 先修好（否则 `InstanceGene.gene_id` 断链，无法可靠追踪"当前对应哪一条 Gene"），用户已确认作为 Task #13 单独跟进，不在本设计范围内处理

## 变更影响范围

| 层 | 文件 | 变更类型 |
|---|---|---|
| DB | `nodeskclaw-backend/app/models/gene.py` | 新增 `lineage_group_id`、`content_updated_at` 字段 + 索引 |
| DB | `nodeskclaw-backend/alembic/versions/<new>.py` | 新增迁移（含并查集回填 `lineage_group_id` + `content_updated_at` 回填脚本） |
| Service | `nodeskclaw-backend/app/services/gene_service.py` | `create_gene` 全新创建分支新增软删记录血缘回接查询；`create_gene` / `fork_gene_to_library` / `publish_variant` / `handle_creation_callback` 传播 `lineage_group_id` + `content_updated_at`；`update_gene` 按字段选择性刷新 `content_updated_at`；新增按 `(visibility, org_id)` 分组的落后检测批量查询（含组织名批量查询）；`_gene_to_dict` / `_list_genes_local` 接入 `newer_sibling_versions` |
| Test | `nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py`（新建） | 传播规则（含软删回接）+ 落后检测测试（含多组织场景） |
| Test | 迁移脚本对应测试 | 并查集回填正确性 |
| 前端 | `nodeskclaw-portal/src/views/GeneMarket.vue` 等技能列表卡片 | 读取 `newer_sibling_versions`，按组织名/scope 展示角标（具体 UI 落地时再定） |
