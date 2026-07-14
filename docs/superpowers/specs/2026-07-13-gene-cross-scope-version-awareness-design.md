# Gene 跨 Scope 版本感知设计文档

**日期**：2026-07-13
**状态**：已批准（v6，作为过渡方案定稿；已知架构局限见"已知架构局限"一节，后续 Repository/Version 拆分作为独立设计跟进）

---

## 已知架构局限（定稿前的架构评审意见，接受为过渡方案的已知代价）

评审中提出一个更根本的架构问题：本设计的 `lineage_group_id` 实际上同时承担了三个职责——**技能身份判断**（这是不是同一个 Skill）、**版本来源判断**（版本链怎么走）、**Fork 血缘判断**（从哪 fork 来）。根因是 `Gene` 用 name/slug 做身份代理，而不是有一个独立、稳定的"Repository"身份（类比 GitHub 的 `owner/repo` 是身份、显示名可以重复不冲突）。这也是本会话里"无关行"这一类 bug 反复出现的根本原因——`create_gene()` 覆盖只能按名字模糊查重，每次都要在具体场景里打补丁（`existing`/`existing_name` 区分、`lineage_group_id` 校验、最终干脆限制"只能上传个人库"）。

**"只允许上传个人库、组织/公共市场只能靠 fork"这条规则本身就是这个根因的一个症状**——如果有稳定的 Repository 身份，直接上传到组织库/公共市场也不需要靠"防止误覆盖无关技能"这个理由来禁止。

**覆盖权限也没有显式的 Maintainer 模型**：现在"fork 回源头覆盖"的审核权限，取的是 `target_gene_id` 那一行的 `org_id`（复用 `review_gene()` 现成的权限判断），这只是"顺带"生效，不是一个显式设计的"谁是这个 Skill 的 owner/maintainer"模型——回答不了"背书组织解散了怎么办"、"能不能有多个 maintainer"这类问题。

**决定**：这是一个独立于本设计的、更大的架构级重构（把 `Gene` 拆分成 `SkillRepository`（稳定身份）+ `Gene`/version（具体版本内容）两层，参考 Git/GitHub 的 repo vs commit 模型），影响面覆盖几乎所有引用 `Gene.id` 的代码，且应该与另一份已批准但未实现的 `docs/superpowers/specs/2026-07-01-skill-version-management-design.md`（`root_gene_id`/`previous_version_id`）合并考虑——两者本质是同一个"身份"问题的两个切面。已跟踪为 Task #14，作为独立的 brainstorming + 设计文档跟进，不阻塞本设计上线。本设计基于 `lineage_group_id` 的方案作为**过渡方案**先落地，接受上述局限。

---

## 背景

Gene（技能）采用 personal / org_private / public 三向 fork 架构：`fork_gene_to_library()` 把一份技能内容复制成一条**完全独立**的新 DB 行，仅通过 `parent_gene_id` 记录"从哪 fork 来"的血缘，之后三份内容互不影响、互不同步。

用户反馈：覆盖个人库里的技能后，组织库/公共市场里由同一个技能 fork 出去的副本不会跟着更新，导致平台上出现"同名但内容版本不一致"的多份拷贝，用户无法感知。

**需求边界**（brainstorming 阶段已与用户确认，不在本次范围内的不要做）：

- 三份记录**仍然保持独立**，不做内容合并/自动同步——fork 出去的副本本来就允许被独立编辑，不能被别人的更新覆盖
- **不提供一键推送更新的操作**，发现版本落后之后，用户走现有的手动覆盖 / fork 覆盖流程去同步（fork 覆盖具体规则见下方"Fork 覆盖支持"一节）
- 只在**当前登录用户自己可见范围**内的血缘副本之间感知版本新旧（自己的 personal fork + 自己所在**所有**组织各自的 org fork + public），不做跨用户的全局血缘感知——例如 A 和 B 各自把同一个公共技能 fork 到自己的个人库，A 更新了自己的个人版本，不应该让 B 看到"有更新"的提示；若用户同时是多个组织成员且这些组织各自独立 fork 了同一血缘，按具体组织分开展示，不合并成一个笼统的"组织库"结论（这条只影响个人库页面里"哪几个组织有更新"的展示粒度——组织库/公共市场页面本身不展示任何提示，见下方"检测方向是单向的"）
- **感知机制是按需拉取（lazy pull），不做主动推送**：管理员覆盖一次组织技能是 O(1) 操作，不会去扫描"谁 fork 过这个技能"；只有某个 forker 自己打开相关列表页时，才会为**这一个用户**触发一次小范围查询。换句话说，fork 的人越多不会让覆盖操作变慢，但没打开页面看的用户也不会被主动告知——这是有意的取舍，见"不在本次范围内"
- 不做内容字节级 diff，只用版本号判断"是否有更新"，不展示具体改了什么
- **只允许直接上传到个人库，组织库/公共市场只能靠 fork 进入**（v3 新增，见下方"上传目标收敛"一节），管理员也不例外
- **检测方向是单向的**（v4 新增，见"版本落后检测"一节）：只检测"组织库/公共市场相较于个人库是否有更新"，只在个人库页面展示提示；反过来"个人库是否领先于组织库/公共市场"不做检测、不提示，组织库/公共市场页面不展示任何版本落后信息，用户如果想知道自己需要对比卡片上的版本号

## 与既有设计的关系

仓库里已有一份**已批准但尚未实现**的设计 `docs/superpowers/specs/2026-07-01-skill-version-management-design.md`，管的是**同一个 scope 内**的版本升级链（`root_gene_id` + `previous_version_id`），并明确把"跨 fork 的版本继承"列为不在范围内。那份设计里也提到了"语义化版本比较"（用于校验新版本 > 当前最新版本），跟本设计要用到的版本号比较逻辑是同一类工具，实现时两边可以共用同一个比较函数，但不强制依赖。

与用户确认：本次设计**独立实现，不依赖也不合并**那份设计——两者是正交的概念（"同一 scope 内技能怎么升级版本" vs "同一技能在三个 scope 之间是否有人已经更新过"）。待 2026-07-01 那份设计真正落地时，需要再评估两者是否有整合空间，但不阻塞本次实现。

---

## 设计迭代记录：为什么放弃时间戳/内容哈希，改用 `version` 字段

v1 版本设计过 `content_updated_at`（时间戳）方案，评审中发现三个实际生产风险：

1. **迁移回填会制造假阳性风暴**：历史 fork 副本的 `created_at` 天然晚于源头，如果回填 `content_updated_at = 各行自己的 created_at`，上线当天所有历史 fork 关系都会显示"有更新"，即使内容从未变过
2. **无变化重传也会误报**：内容一字未改的重新上传，时间戳依然会刷新，触发不必要的提示
3. **迁移风暴修好之后还有"badge 疲劳"风险**：没有内容比对、没有同步/清除机制，团队正常迭代下"有更新"角标会长期挂着，逐渐变成用户会无视的噪音

也评估过用"内容哈希"代替时间戳（能解决前两条），但会引入哈希计算/存储的额外实现面。

**最终方案**：`Gene` 表本身已经有 `version` 字段（`String(16)`，默认 `"1.0.0"`），只是目前所有上传入口都没真正让用户填写它，永远是默认值，形同虚设。让这个字段承担版本判定职责：

- **历史数据天然正确**：所有存量数据的 `version` 都是未曾改动过的 `"1.0.0"`，同血缘内历史上没被真正区分过版本，迁移不需要任何回填计算——不会重演时间戳方案的上线风暴
- **是否算"更新"交给上传的人判断**：覆盖时强制用户手动输入新版本号（校验大于等于旧版本号，只拦截倒退），内容没真的变就可以保持原版本号不变，不会被自动判定为"有更新"
- **不需要额外的哈希基础设施**，只是比较一个已存在的短字符串

---

## 上传目标收敛：只能上传到个人库，组织库/公共市场只能靠 fork

### 起因

评审中发现一个真实的时序漏洞：普通用户直接上传技能到组织库需要走审核（`review_status=pending_owner`），但 `create_gene()` 的"覆盖"判断是按**名字**匹配，不看血缘——如果组织里已经存在一条**名字相同但完全不相关**的技能（比如恰好撞名，来源、内容、创建者都毫无关系），用户上传时勾选覆盖，会在提交的那一刻（不是审核通过的那一刻）就把这条无关技能软删掉，管理员事后审核只是决定"新内容要不要生效"，完全无法阻止"旧内容已经被删"这个既成事实——哪怕审核拒绝，旧技能也回不来了。

`fork_gene_to_library()` 不会有这个"血缘不相关"的问题，因为 fork 有明确的 `source`，可以直接比较 `lineage_group_id` 拒绝不相关的覆盖（见下方"Fork 覆盖支持"）。但 `create_gene()`（直接上传）没有这样一个"源头"可以校验，只能按名字/slug 硬匹配，这个模糊性无法从根上消除。

### 决定：直接上传只能落个人库，组织库/公共市场的内容必须来自 fork

- `/genes/upload-folder`、`/genes/manual` 两个直接上传入口，**不再接受 `target=org`/`target=public`**，只接受 `target=personal`（含管理员/超管，没有例外——这样才能保证组织库/公共市场里的每一条记录都有明确血缘可查）
- 想把技能放进组织库/公共市场，统一走 `fork_gene_to_library()`：先上传/维护好个人库那份，再 fork 过去；组织库本身要更新时，也是"更新自己的个人库副本 → fork 覆盖同步过去"，而不是直接对着组织库重新上传
- 这样一来，组织库/公共市场里出现的"同名冲突"必然发生在 fork 场景，而 fork 天然有 `source` 可以比对 `lineage_group_id`，从根上避免了"不相关技能被误覆盖"这类问题；`create_gene()` 自己的覆盖逻辑因此只需要处理 personal scope 内的同名冲突（用户自己名下的技能重名，影响范围仅限自己），不再需要面对"组织库里出现无法验证血缘的覆盖请求"这个难题

---

## 核心设计决策

### 用 `lineage_group_id` 分组，而非实时回溯 `parent_gene_id` 链

新增 `Gene.lineage_group_id` 字段，作为一个不透明的分组 key（不是外键，不要求指向一条现存活的行）。同一血缘下的 personal/org/public 副本共享同一个 `lineage_group_id`，查询"某技能的所有血缘副本"变成 `WHERE lineage_group_id = X`，可以在列表页批量查询（`WHERE lineage_group_id IN (...)`），避免逐条实时回溯 `parent_gene_id` 链带来的 N+1 查询。

### Fork lineage 与 Variant lineage 分离

`parent_gene_id` 目前被 `fork_gene_to_library()`（三向 fork）和 `publish_variant()` / `handle_creation_callback()`（AI 进化出的 variant）共用，语义混合。

`lineage_group_id` 只服务"三向 fork"这一个概念：

- Fork 出来的副本**继承**源的 `lineage_group_id`
- Variant 是进化出的新技能，语义上不是"同一个技能换了个 scope"，**不继承**父技能的 `lineage_group_id`，用自己的新 id 单独成组

### 不做"软删记录血缘回接"（已知限制，明确接受）

早期方案里曾设计过"先删除个人库技能、再重传同名技能时，自动回接到软删前那条记录的血缘"，评审中发现这是一个不可靠的启发式——纯按 slug/name 字符串匹配，无法区分"重传同一个技能"和"纯属巧合、删掉一个技能后又传了个碰巧同名的全新技能"，尤其是通用技能名字（"客服助手"之类）复用概率不低，一旦匹配错误会把两个毫不相关的技能强行关联到同一血缘，且没有任何机制能让用户发现或纠正这个错误关联。

**决定放弃**：删除再重传一律视为全新技能，不做自动关联。用户如果需要保留血缘关系，应该用"覆盖"（`overwrite=True`）而不是"先删除再传"——覆盖本身就有干净、可验证的血缘传播逻辑。

---

## 覆盖（overwrite）时的版本号机制

### `create_gene()` 覆盖分支：强制输入新版本号

当前 `create_gene()` 的 `req.version` 字段有默认值 `"1.0.0"`，覆盖时前端从不真正传值。改造后：

- 前端"是否覆盖"确认弹窗新增一个版本号输入框，**预填建议值**（在当前版本号基础上自动 +1 patch，如 `1.0.0` → `1.0.1`），用户可以直接接受建议值，也可以手动改成任意合法版本号，或者保持跟旧版本号一致（表示"内容没有实质变化，只是想覆盖一下"）
- 后端 `create_gene()` 覆盖分支新增校验：**新版本号必须语义化版本比较「大于等于」被覆盖那一行的当前版本号**（如 `1.10.0 >= 1.9.0`、`1.0.0 >= 1.0.0` 均通过），只拦截"版本号倒退"这一种情况（新版本号严格小于旧版本号才拒绝）——保持版本号不变是合法操作，覆盖仍然成功，只是这次覆盖不会让"版本落后感知"认为内容变了（因为版本号确实没变）
- 版本号解析失败（不是合法的 `X.Y.Z` 格式）时的兜底：拒绝请求，提示版本号格式不合法——覆盖操作本来就需要用户主动填写，直接要求合法格式比静默兜底更安全

**上线排查**：`create_gene(overwrite=True)` 目前有 3 个入口——`/genes/upload-folder`（主入口，前端从不传 `version`，落到 schema 默认 `"1.0.0"`）、`POST /admin/genes`（管理台，`version` 由请求体决定）、`/genes/manual`（不支持 `overwrite`，恒为 `False`，不受影响）。改成"大于等于"校验后，只有当被覆盖行的 `version` 已经被**其他入口**（比如管理台）bump 到比默认值更高、而这次覆盖又没有显式传新版本号时才会被拦下——多数场景下不会误伤，但 `upload-folder` 的 `version` 参数改造必须和前端弹窗同批上线，不能后端先上、前端还没接入版本号输入框，否则旧前端不传 `version`、被覆盖行版本号又已经更高的场景会被新校验拒绝且报错文案容易让用户误解为"改动无效"。

### 语义化版本比较工具

新增一个轻量的版本比较函数（后端 Python + 前端 TS 各一份，逻辑一致）：拆成 `(major, minor, patch)` 三元组按数值比较；解析失败时的行为：写入时（覆盖校验）直接拒绝，读取时（列表页比较展示）退化为"跳过比较，不计入落后判断"，不假装知道谁新谁旧。

---

## Fork 覆盖支持

### 现状缺口

`fork_gene_to_library()` 目前只支持"目标 scope 无同名技能"的全新 fork；一旦目标 scope 已有同名技能，直接 `ConflictError` 拒绝，没有覆盖选项。这意味着"看到某个 scope 有更新版本"之后，如果用户想通过 fork 把新版本同步过来，会因为目标 scope 已经有旧版本同名技能而卡住，只能先手动删除旧版本再 fork——违背了"手动同步应该走得通"的初衷。

### 新增 `overwrite` 参数

`fork_gene_to_library(db, source_identifier, target, *, overwrite: bool = False, ...)`：

判断顺序（**不管 `overwrite` 是否为 `True`，无关行保护始终生效**）：

1. 目标 scope 按名字查有没有同名技能（`existing_name`，沿用现有的 2.5 节查重逻辑）
2. 没有同名技能 → 走原有的全新 fork 逻辑，不受本次改动影响
3. 有同名技能，但 `existing_name.lineage_group_id != source.lineage_group_id`（名字撞车，血缘不相关）→ **无论 `overwrite` 是否为 `True`，一律 `ConflictError` 拒绝**，当作无关技能保护起来，避免一个毫不相关的技能被误覆盖
4. 有同名技能，且 `lineage_group_id` 相同（确认是同一技能的另一份、只是版本可能落后）：
   - `overwrite` 为 `False` → 按现状报错"技能名称已存在"，不改变现有行为
   - `overwrite` 为 `True`，先比较 `source.version` 与 `existing_name.version`：
     - `source.version` 与 `existing_name.version` **相等** → 抛专门异常 `errors.gene.fork_already_up_to_date`，前端识别成"已是最新版本，无需同步"（信息型提示），不创建新行、不软删旧行
     - `source.version` 严格小于 `existing_name.version` → 拒绝，`errors.gene.fork_version_regression`，提示"目标版本更新，无法覆盖为旧版本"
     - `source.version` 严格大于 `existing_name.version` → 校验通过，接下来**按目标 scope 是否需要审核分两条路径处理**（见下一节）

### 按目标 scope 分流：personal 立即执行，org/public 走审核暂存

版本校验通过之后，"真正执行覆盖"（软删旧行、插入新行、重接引用）这个动作要不要立即发生，取决于目标 scope 要不要审核：

- **`target == "personal"`**：personal scope 不需要审核，维持原有行为——立即软删 `existing_name`、插入新行、拷贝 `source.version`、重接 `InstanceGene`/`OrgRequiredGene` 引用，一步到位
- **`target in ("org", "public")`**：这两个 scope 需要组织 admin 审核（**管理员/超管本次也不例外**，见"上传目标收敛"一节），版本校验通过后**不立即修改 `genes` 表**——不软删 `existing_name`，也不插入新的 Gene 行，而是创建一条 `GeneOverwriteSubmission`（见下方"覆盖审核暂存"）记录本次提交的完整内容，返回给调用方"已提交，等待管理员审核覆盖"。真正的软删+插入，等到管理员审核通过那一刻才执行

**注意：这里的"管理员/超管不例外"专门指覆盖审核这一步，不是"上传目标收敛"那条规则的重复**——现有 `resolve_target_attrs`/`bypass_review` 逻辑（"操作者本身是目标 org 的 admin 或平台超管时自动免审、直接 approved"）不适用于 `GeneOverwriteSubmission` 的审核。哪怕提交覆盖的人自己就是这个组织的 admin，也必须走"提交 → 去审核队列单独点确认"两步，不会一步到位自动生效。这是有意为之：把"上传即生效"的单击操作拆成两个独立动作，即使这两个动作最终是同一个人做的，也能防止手滑一次性删掉旧内容、没有反悔的机会——这正是本节要解决的"审核拒绝无法恢复被覆盖内容"时序问题的核心，如果管理员自己能一键跳过确认，这个防护就形同虚设。

这样解决了"审核拒绝无法恢复被覆盖内容"的时序问题：拒绝的话，`existing_name` 那一行从始至终没被动过，什么都不会丢。

---

## 覆盖审核暂存（`GeneOverwriteSubmission`）

### 为什么不能直接在 `genes` 表里"先插入一条 pending 行，审核通过再删旧行"

`genes` 表的 partial unique index（`uq_genes_name_org_active`/`uq_genes_slug_org_active`）语义是"同一 scope 内，任意时刻只能有一条**未软删**的同名/同 slug 记录"，不区分审核状态——如果不软删旧行就先插入一条同名的新行（哪怕状态是 pending），会直接撞上这两条唯一索引，插不进去。要让"待审核的新内容"和"已批准的旧内容"在数据库层面同时存在，要么大改现有查重的唯一索引语义（影响面大，可能引入新的竞态需要重新梳理），要么把待审核内容放到一张**独立的表**里，不占用 `genes` 表的唯一索引位置。选后者。

### 新表：`gene_overwrite_submissions`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `String(36)`，主键 | 沿用 `BaseModel` 惯例 |
| `target_gene_id` | `String(36)`，非空 | 本次提交打算替换掉的那一条 `Gene.id`（也就是 `existing_name`） |
| `source_gene_id` | `String(36)`，可空 | fork 源头 gene 的 id（本地来源时有值，外部聚合器来源时为空） |
| `lineage_group_id` | `String(36)`，非空 | 继承自 `source`，approve 时原样赋给新插入的 Gene 行 |
| `name` / `slug` / `description` / `short_description` / `category` / `tags` / `source` / `source_ref` / `icon` / `version` / `manifest` / `dependencies` / `synergies` | 与 `Gene` 对应字段同类型 | 本次提交要写入的完整内容快照，approve 时原样搬进新的 `Gene` 行 |
| `visibility` / `org_id` / `created_by` | 与 `Gene` 对应字段同类型 | 目标归属（`resolve_target_attrs` 算出来的） |
| `review_status` | `String(16)` | 复用 `GeneReviewStatus`：`pending_owner` → `approved`/`rejected` |
| `reject_reason` | `Text`，可空 | 拒绝原因 |

不需要 `is_published` 字段——这张表里的记录永远代表"还没生效的提议"，approve 之后内容被搬进 `genes` 表、`is_published` 才有意义。

### 提交（fork 覆盖命中 org/public 且版本校验通过时）

```python
submission = GeneOverwriteSubmission(
    target_gene_id=existing_name.id,
    source_gene_id=source.id if source is not None else None,
    lineage_group_id=source.lineage_group_id,
    name=source_name, slug=new_slug, description=source_description, ...,
    version=source_version,
    visibility=attrs["visibility"], org_id=attrs["org_id"], created_by=attrs["created_by"],
    review_status=GeneReviewStatus.pending_owner,
)
db.add(submission)
await db.commit()
```

`existing_name`、`genes` 表本身完全不受影响，`fork_gene_to_library()` 这次调用返回的不是一个 `Gene` 字典，而是一个"提交成功，等待审核"的结果（前端据此提示用户，不能当成 fork 已经完成）。

### 审核：`review_gene_overwrite_submission(db, submission_id, action, reason=None, *, current_user)`

权限校验跟 `review_gene()` 完全一致（该 gene 所属 org 的 admin 或平台超管；这里"该 gene"取 `target_gene_id` 指向的那一行的 `org_id`），**但不复用 `bypass_review`**——`review_gene_overwrite_submission()` 没有"提交者本身是 admin 就自动免审"这条捷径，提交和审核永远是两个独立的动作，即使是同一个人做的。

**`action == "reject"`**：`submission.review_status = rejected`，写 `reject_reason`；`target_gene_id` 那一行**完全不受影响**，到此结束。

**`action == "approve"`**：先做一次**过期重新校验**（应对竞态——审核排队期间，`target_gene_id` 那一行可能已经被别的、更早批准的提交替换掉了）：

1. 重新查 `target_gene_id` 当前状态：如果这一行已经不是"未软删"（被别的已批准提交替换掉了），或者它当前的 `lineage_group_id` 已经不等于 `submission.lineage_group_id`（说明血缘关系在排队期间发生了变化，理论上不应该发生，但保守起见一并校验），**这次提交视为过期**：`submission.review_status = rejected`，`reject_reason` 自动填"目标技能已发生变化，请重新提交"，返回一个能让前端区分"过期自动拒绝"和"管理员主动拒绝"的结果（比如带一个 `stale: true` 标记），**不算审核失败，是正常的竞态处理**
2. 过期校验通过（`target_gene_id` 那一行仍然是提交时的那一份、未软删、血缘未变）：重新用 `submission.version` 对比这一行**当前**的 `version`（不是提交时缓存的版本号，用当前值重新比一次，因为排队期间它也可能被合法地又更新过一次），严格大于才继续，否则同样按"过期"处理
3. 通过：`old_gene_id = target.id`；`target.soft_delete()`；用 `submission` 存的内容构造新的 `Gene(...)` 插入（`is_published=True`, `review_status=approved`）；`_rewire_gene_references(db, old_gene_id, new_gene.id)`（复用 Task #12 已有的机制）；`submission.review_status = approved`
4. 若公共可见性还需要推送外部注册表，复用 `review_gene()` 里 `_push_approved_gene_to_registry` 的逻辑

### 管理员审核列表：合并展示

现有 `GET /admin/genes/pending-review` 只查 `Gene.review_status IN (pending_owner, pending_admin)`。改造后同时查 `GeneOverwriteSubmission.review_status IN (pending_owner, pending_admin)`，两类结果合并返回，每条记录带一个 `kind: "new" | "overwrite"` 字段区分；`kind == "overwrite"` 的记录额外带上：

```json
{
  "kind": "overwrite",
  "target_gene_id": "...",
  "target_gene_name": "客服助手",
  "target_gene_version": "1.0.0",
  "proposed_version": "1.1.0",
  ...
}
```

前端审核队列页面在同一个列表里渲染，`kind == "overwrite"` 的条目额外展示"将替换：客服助手 v1.0.0 → v1.1.0"这类提示，让管理员在批准前看到"这次操作会顶掉一条现有记录"。

### 为什么 fork 覆盖不需要版本号输入框

`create_gene()` 覆盖时用户在上传**新内容**，只有他自己知道这次改了什么、该标多少版本号，所以需要手动输入。而 fork 覆盖搬运的是**已经有版本号的现成内容**（源头的当前版本），不存在"这次改了什么"的问题，直接复用源头版本号即可，语义更清晰也更省事。

---

## 数据模型

### Gene 表新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `lineage_group_id` | `String(36)`，索引，非 FK | 分组 key，同一血缘下的三向副本共享同一个值 |

`version` 字段已存在，不需要新增列。`lineage_group_id` 不加唯一约束（同组允许多行），加普通索引支持 `WHERE lineage_group_id IN (...)` 批量查询。

### 新表：`gene_overwrite_submissions`

字段定义见上方"覆盖审核暂存"一节，用于暂存"fork 覆盖 org/public 且需要审核"这一类提交，approve 时才把内容搬进 `genes` 表。

### 传播规则

| 路径 | `lineage_group_id` 取值 | `version` 取值 |
|---|---|---|
| `create_gene()` 全新创建（无冲突，只会发生在 personal scope，见"上传目标收敛"） | 自己的新 id（构造时 Python 端 `BaseModel.id` 已用 `default=lambda: str(uuid.uuid4())` 生成，构造对象时即可直接引用） | 用户请求里的 `version`（默认 `"1.0.0"`） |
| `create_gene()` overwrite 分支（同上，只会发生在 personal scope） | 继承被软删那一行的 `lineage_group_id`（在调用 `target.soft_delete()` 之前先读出 `target.lineage_group_id`） | 用户手动输入的新版本号，校验大于等于旧版本号（只拦截倒退） |
| `fork_gene_to_library()` 全新 fork（目标无同名） | 继承 `source.lineage_group_id` | 拷贝 `source.version` |
| `fork_gene_to_library()` 覆盖 fork，`target == "personal"`（无关行保护 + 版本校验通过） | 立即继承 `source.lineage_group_id`（此时通常与被覆盖行的 `lineage_group_id` 本就相同） | 立即拷贝 `source.version`；源版本等于目标现有版本时不创建新行（提示"已是最新"）；源版本更低则拒绝 |
| `fork_gene_to_library()` 覆盖 fork，`target in ("org", "public")`（无关行保护 + 版本校验通过） | 校验通过时先写进 `GeneOverwriteSubmission.lineage_group_id`，**approve 时才**赋给新插入的 Gene 行 | 同上先写进 submission，approve 时才拷贝进新行 |
| `publish_variant()` / `handle_creation_callback()` | **不继承**，用自己的新 id 单独成组 | 各自默认逻辑，不受本设计影响 |

`/admin/genes/{gene_id}` 就地编辑（`PUT`，`update_gene()`）不创建新行，`lineage_group_id` 不受影响；若这条编辑改了 `version` 字段，直接以编辑后的值参与后续比较，不需要额外规则。**已知覆盖盲区**：这个接口可以直接改 `manifest`/`description`/`name` 等内容字段，但本设计没有要求这条路径也必须同步 bump `version`——如果调用方改了内容却没改版本号，这次真实的内容变化会完全绕开整套版本感知机制。核实过 `nodeskclaw-portal` 目前没有任何前端界面调用这个内容编辑接口（只有审核通过/拒绝的 `PUT .../review`），所以现阶段不是活跃风险，但接口本身没有防护，记录为已知限制，见"不在本次范围内"。

### Alembic 迁移

只需要给 `lineage_group_id` 做一次性回填，不涉及 `version`（复用现有字段，历史值天然正确）：

1. Python 端并查集（union-find）——取出所有 Gene 的 `(id, parent_gene_id)`，沿 `parent_gene_id` 建无向连通分量（一条链无论朝哪个方向 fork 都会被分到同一组；variant 也会被历史数据误连进来——见下方"已知限制"），每个连通分量选一个稳定代表值作为该组的 `lineage_group_id`（用分量内最小的 `id` 字符串，保证确定性、可重复运行）
2. 孤立节点（无 `parent_gene_id` 且没有任何行以它为 `parent_gene_id`）各自成组，`lineage_group_id = 自己的 id`
3. 新增列先允许 `NULL`，批量 `UPDATE` 后改为 `NOT NULL`

**已知限制**：由于当前 `parent_gene_id` 混用于 fork 和 variant 两种语义，历史数据回填时无法百分百区分"这条 parent_gene_id 链是三向 fork 还是 AI 进化出的 variant"——回填会保守地把两者都视为同一分量处理。这只影响**回填那一刻已存在的历史行**；回填完成之后，新产生的数据严格按上表的传播规则处理，variant 和 fork 走向分离。回填前会跑一次统计（有多少历史行的 `parent_gene_id` 链同时包含 fork 产物和 variant 产物），如果数量很小可以接受，数量大再考虑单独处理。

---

## 版本落后检测

### 判定信号：`version`（语义化版本比较）

**单向检测，只在个人库这一侧计算**：Gene G 判定为"落后"，当且仅当 **G 本身是 personal scope**（`G.visibility == "personal"`），且存在一条与 G 同 `lineage_group_id`、未软删、`visibility` 为 `org_private` 或 `public`、且对当前登录用户可见的兄弟 S，满足 `S.version` 语义化版本号严格大于 `G.version`。

反过来——查看组织库/公共市场的技能卡片时，**不计算、不展示**任何"落后"提示，哪怕当前用户自己的个人库版本更新。这是有意的单向设计：只能通过上传个人库再 fork 出去（见"上传目标收敛"），个人库是编辑的起点，"组织库/公共市场是否比我的个人库新"是用户会主动关心的信息；反过来"我的个人库是否比组织库/公共市场新"不做主动提示，用户如果想知道，自己对比卡片上的版本号即可。

"可见"复用现有权限模型（这里只用于判断 S，即 org_private/public 的兄弟，是否对当前用户可见）：
- `visibility = public` → 任何登录用户可见
- `visibility = org_private` → 仅当前用户所在组织（`org_id` 匹配当前用户的组织成员关系）

**分组粒度是 `(visibility, org_id)` 而不是只有 `visibility`**：同一个技能可能在用户所在的多个组织里各自被独立 fork，这种情况下不能把多个组织的副本合并成一个"org_private"笼统结论——分别标出组织名。`public` 天然全局一份，只有 `org_private` 需要按 `org_id` 再拆一层。

**待审核的覆盖提交不计入检测**：`GeneOverwriteSubmission` 是独立的表，不在 `genes` 表里，上面的查询天然不会扫到它——也就是说，一次 org/public 覆盖提交只要还没被管理员批准，就不会让"版本落后"提示提前出现（提前显示"有更新"会误导用户以为已经生效，实际内容还没变）。批准之后旧行被替换，下次查询自然能看到新版本号，不需要额外处理。

### 查询方式（供列表页使用）：应用层比较，不用 SQL `MAX()`

`version` 是自由文本字段，SQL 的字符串 `MAX()` 是字典序比较，对语义化版本号是错的（`"1.9.0"` 字典序大于 `"1.10.0"`，数值上反了）。由于一页列表里同血缘的兄弟数量很少（少数几个组织 + 公共市场，通常不超过个位数），不需要 SQL 聚合，直接拉取所有候选行、在应用层比较：

1. 收集本页所有 **`visibility == "personal"`** 的 Gene 的 `lineage_group_id`（`org_private`/`public` 的 Gene 直接跳过，`newer_sibling_versions` 恒为空数组，不查询、不计算——这样也顺带减小了查询范围）
2. 一次查询：`SELECT lineage_group_id, visibility, org_id, version FROM genes WHERE lineage_group_id IN (...) AND deleted_at IS NULL AND visibility IN ('org_private', 'public') AND <可见性过滤>`（`org_private` 的可见性过滤限定在当前用户所在的组织 id 集合内）——不聚合，取全部匹配行
3. 若结果里出现 `org_private` 分组，批量查一次涉及到的 `org_id` 对应的组织名（`Organization` 表），用于展示
4. 内存中按 `lineage_group_id` 分组，组内每条记录跟对应的 personal Gene 做语义化版本比较
5. 逐条比较：某条 personal Gene 的落后列表 = 上述结果里，`version` 语义化比较严格更新的那些 `org_private`/`public` 条目

### API 输出

Gene 序列化字段（`_gene_to_dict`）新增只读字段 `newer_sibling_versions`（结构化数组，按具体组织区分）：

```json
"newer_sibling_versions": [
  {"visibility": "personal", "org_id": null, "org_name": null, "version": "1.2.0"},
  {"visibility": "org_private", "org_id": "org-a-id", "org_name": "研发部", "version": "1.1.0"},
  {"visibility": "org_private", "org_id": "org-b-id", "org_name": "市场部", "version": "1.0.0"},
  {"visibility": "public", "org_id": null, "org_name": null, "version": "1.0.5"}
]
```

空数组表示没有更新的血缘副本。个人库、组织库、公共市场列表目前都走同一个 `list_genes()` → `_list_genes_local()` → `_gene_to_dict()` 路径，改一处即可覆盖三处列表。

前端拿到这个字段后按 `visibility`/`org_name`/`version` 拼文案（如"研发部有 v1.1.0 版本"），本次不规定具体 UI 文案/组件实现细节，由前端按现有卡片角标样式风格实现（图标走 `lucide-vue-next`，不用 emoji）。

### 场景验证

**场景一**：A 上传技能 v1.0.0 到个人库 → fork 到组织 X（组织副本拷贝 v1.0.0）→ 组织 X 的另一个成员 B 把这份技能 fork 到自己的个人库（B 的个人副本也是 v1.0.0）并修改后重新上传为 v1.1.0：

- A 的个人副本（v1.0.0）、组织 X 副本（v1.0.0）：版本号一致——A 打开自己的个人库页面，**无提示**
- B 修改后的个人副本（v1.1.0）：`visibility=personal, created_by=B`，只在 B 自己的可见范围内，A 看不到，不受影响
- B 打开自己的个人库页面（v1.1.0）时，B 可见范围内的组织 X 副本、公共市场副本都还是 v1.0.0，版本号比 B 的个人库旧——**因为检测是单向的（只看"组织库/公共市场是否比个人库新"，不看反过来）**，B 这边不会有任何提示；B 想知道"组织库落后了"，需要自己对比组织库页面上显示的版本号
- 若干时间后 B 打开**组织 X 的技能库页面**，看到的是组织 X 那条 v1.0.0 记录本身（照常显示），**不会有任何"落后"提示**——组织库/公共市场页面从不展示落后检测结果，这是本次设计的单向取舍

**场景二**：管理员直接更新组织 X 的技能到 v1.1.0（没有先经过个人库——但按"上传目标收敛"，这只能通过 fork 覆盖发生，不是直接改组织库）：

- 组织 X 副本变成 v1.1.0，A 的个人副本仍是 v1.0.0
- A 打开**个人库页面**时，看到"组织 X 有 v1.1.0"提示（个人库版本落后于组织库，属于本次设计要检测的方向）
- A 想同步：用 fork 覆盖——`fork_gene_to_library(source=组织X的Gene, target="personal", overwrite=True)`，校验 v1.1.0 > A 现有个人副本的 v1.0.0，通过后覆盖 A 的个人副本为 v1.1.0，提示消失

**场景三**：A 更新了自己的个人库版本到 v1.2.0，想同步到组织 X（组织 X 现有版本 v1.1.0，血缘相同）：

- A 发起 `fork_gene_to_library(source=A的个人Gene, target="org", overwrite=True)`，`target == "org"` 需要审核，版本校验 v1.2.0 > v1.1.0 通过 → 创建一条 `GeneOverwriteSubmission`（不改动 `genes` 表），A 收到"已提交，等待管理员审核"
- 此时组织 X 的技能列表里，那条 v1.1.0 的记录**照常显示、照常可用**；A 打开自己的个人库页面（v1.2.0）也不会看到任何提示——单向检测只提示"组织库/公共市场是否比个人库新"，A 的个人库本身已经是最新，没有"落后"这回事，跟组织库还没跟上没关系
- 组织 X 的管理员打开审核队列，看到这条 `kind="overwrite"` 的记录，提示"将替换：该技能 v1.1.0 → v1.2.0"
  - 批准 → 组织 X 的 v1.1.0 行被软删，新的 v1.2.0 行创建并生效，已安装该技能的实例引用自动重接
  - 拒绝 → 组织 X 的 v1.1.0 行完全不受影响，A 的这次提交被标记为已拒绝，A 需要的话可以重新发起提交


---

## 测试计划

- **传播规则**：`create_gene` 全新创建独立成组，`version` 取请求值；`create_gene` overwrite 继承旧组，新版本号大于等于旧版本号均允许提交（相等=合法的"不算新版本"覆盖），仅版本号倒退或格式不合法时拒绝；`fork_gene_to_library` 全新 fork 继承源组 + 拷贝源版本号；`publish_variant` / `handle_creation_callback` 不继承、独立成组
- **上传目标收敛**：`/genes/upload-folder`、`/genes/manual` 传 `target=org`/`target=public` 应该被拒绝（包括管理员/超管身份，没有例外），只接受 `target=personal`
- **`create_gene` overwrite 版本号大于等于场景**：保持原版本号覆盖应成功（不是被拒绝），新行 `version` 与旧版本号相同，落后检测因此不会误报"有更新"
- **`create_gene(overwrite=True)` 其他调用方兼容性**：`POST /admin/genes` 这类内部/管理台入口仍可能传 `overwrite=True`，回归测试确认"大于等于"新规则的实际表现符合预期
- **fork 覆盖的无关行保护**：目标 scope 同名但 `lineage_group_id` 不同的行，无论 `overwrite` 是否为 `True` 都应 `ConflictError`，且该行不受任何影响（不被软删）
- **fork 覆盖的版本号三态**：源头版本号严格更新 → 继续往下走（personal 立即覆盖 / org-public 生成 submission）；源头版本号与目标相等 → 返回"已是最新版本"提示，不创建新行、不软删旧行、不生成 submission；源头版本号更低 → 拒绝，旧行不受影响
- **fork 覆盖 personal 目标**：版本校验通过后立即软删旧行、插入新行、重接引用，行为与 v2 设计一致
- **fork 覆盖 org/public 目标 —— 提交阶段**：版本校验通过后只创建 `GeneOverwriteSubmission`，`genes` 表里 `existing_name` 那一行必须原封不动（未软删、`review_status`/`is_published` 都不变）
- **fork 覆盖 org/public 目标 —— 审核通过**：`review_gene_overwrite_submission(action="approve")` 后，旧行被软删，新行按 submission 内容创建（`is_published=True`, `review_status=approved`），`InstanceGene`/`OrgRequiredGene` 引用重接到新行
- **fork 覆盖 org/public 目标 —— 审核拒绝**：`review_gene_overwrite_submission(action="reject")` 后，旧行完全不受影响（仍然活跃、内容不变），submission 标记为 `rejected`
- **fork 覆盖 org/public 目标 —— 审核时过期重新校验**：构造"提交后、审核前，`target_gene_id` 已经被另一条已批准的 submission 替换掉"的场景，approve 这条过期 submission 应该自动转为 `rejected`（`reject_reason` 提示"目标技能已发生变化"），不应该报服务器错误，也不应该误伤已经替换成功的新行
- **管理员审核列表合并**：`GET /admin/genes/pending-review` 返回结果同时包含 `kind="new"`（普通待审核 Gene）和 `kind="overwrite"`（待审核的覆盖提交，带 `target_gene_name`/`target_gene_version`/`proposed_version`）两类条目
- **覆盖审核不接受 admin 免审捷径**：提交覆盖的用户自己就是该组织 admin（甚至平台超管）时，提交后 submission 依然是 `pending_owner`，不会因为 `is_user_admin_of_org`/`bypass_review` 而自动变成 `approved`——必须显式调用 `review_gene_overwrite_submission(action="approve")` 才生效，即使调用者和提交者是同一个人
- **落后检测**：只对 `visibility=personal` 的 Gene 计算 `newer_sibling_versions`，`org_private`/`public` 的 Gene 恒为空数组（不查询）；个人库版本更新后，`org_private`/`public` 的版本号更新能被个人库正确感知到；只有部分 scope 存在血缘副本时不误报；同一血缘在用户所在的多个组织里各自独立 fork 时，个人库页面的 `newer_sibling_versions` 按 `org_id` 分开列出各自版本号，用户不是成员的组织的副本即使同血缘也不出现在结果里
- **版本号比较工具**：`1.10.0 > 1.9.0`、`1.0.0 == 1.0.0`、格式不合法时的降级行为（写入拒绝 / 读取跳过比较），前后端两份实现结果一致
- **迁移回填**：构造链式（personal→org→public 单向 fork）、多分支（一条 public 被 fork 到两个不同 org）、孤立三种历史数据形状，验证并查集分组结果符合预期且迁移可重复运行（幂等）

## 不在本次范围内

- 任何自动或一键推送更新的操作（fork 覆盖仍然是用户主动发起的手动操作，不是自动同步）
- 跨用户的全局血缘感知（只看当前用户自己可见范围内的血缘副本），也不做主动推送通知——用户不主动打开相关页面就不会被告知，这是"按需拉取、零写扩散"模型的固有取舍，若未来要做主动提醒需要异步批处理的通知基础设施，作为独立功能评估
- 内容字节级 diff（只判断版本号是否更新，不展示具体改了什么）
- 与 2026-07-01 版本管理设计的整合（该设计尚未落地，本次独立实现，但版本号比较工具可共用）
- "先删除再重传"的血缘自动回接（已知限制，明确不做，删除后重传视为全新技能）
- 组织与组织之间的"谁该以谁为准"仲裁——多个组织各自独立 fork 后各自演化是允许的正常状态，本设计只负责告知"存在更新的血缘副本"，不评判哪个版本更权威
- 已安装到实例上的技能与源 Gene 的更新同步/引用修复——这是一个独立的、本次改动之前就存在的 bug（`create_gene()` overwrite 导致 `InstanceGene.gene_id` 断链），已作为 Task #12 修复完成，不在本设计范围内
- 实例已装技能感知源 Gene 更新——本设计的"落后检测"只覆盖个人库/组织库/公共市场三方之间的库内对比，不覆盖"已经装到 AI 员工实例上的技能，相对当初安装来源是否已经过时"，作为 Task #13 单独跟进
- `PUT /admin/genes/{gene_id}`（`update_gene()`）修改内容字段时不强制要求同步 bump `version`——这是一个已知的后端能力层面覆盖盲区（细节见"数据模型"一节），已核实 `nodeskclaw-portal` 目前没有任何前端调用这个内容编辑接口，现阶段不是活跃风险，本次不修，若未来有 UI 接入这个接口需要重新评估是否要补上版本号强制校验
- `GeneOverwriteSubmission` 的"待审核提交本身也可能过期堆积"（比如提交后源头一直没人处理）不做定期清理/过期作废机制，本次只处理"审核时发现已过期"这一种情况，不做主动清理

## 变更影响范围

| 层 | 文件 | 变更类型 |
|---|---|---|
| DB | `nodeskclaw-backend/app/models/gene.py` | 新增 `lineage_group_id` 字段 + 索引 |
| DB | `nodeskclaw-backend/app/models/gene_overwrite_submission.py`（新建） | `GeneOverwriteSubmission` 模型 |
| DB | `nodeskclaw-backend/alembic/versions/<new>.py` | 新增迁移（并查集回填 `lineage_group_id` + 新建 `gene_overwrite_submissions` 表） |
| Service | `nodeskclaw-backend/app/services/gene_service.py` | `create_gene` overwrite 分支新增版本号校验（仅 personal scope）；`fork_gene_to_library` 新增 `overwrite` 参数 + 无关行保护 + 版本号三态校验 + 按 target 分流（personal 立即执行 / org-public 生成 submission）；`resolve_target_attrs`/`create_gene` 调用方收紧到只接受 `target=personal`；新增 `review_gene_overwrite_submission()`；`review_gene()` 所在的 pending-review 查询逻辑合并 `GeneOverwriteSubmission`；`create_gene` / `fork_gene_to_library` / `publish_variant` / `handle_creation_callback` 传播 `lineage_group_id`；新增语义化版本比较工具函数；新增按 `(visibility, org_id)` 分组的落后检测批量查询（含组织名批量查询）；`_gene_to_dict` / `_list_genes_local` 接入 `newer_sibling_versions` |
| API | `nodeskclaw-backend/app/api/genes.py` | `upload_gene_folder`/`create_manual_gene` 收紧 `target` 校验（拒绝 org/public）；fork 接口新增 `overwrite` 参数；`GET /admin/genes/pending-review` 合并展示两类待审核记录 |
| API | `nodeskclaw-backend/app/api/genes.py` | 新增 `PUT /admin/gene-overwrite-submissions/{submission_id}/review` 端点（复用 `review_gene()` 的权限校验模式） |
| Test | `nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py`（新建） | 传播规则 + 落后检测测试（含多组织场景、fork 覆盖场景） |
| Test | `nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py`（新建） | 覆盖审核暂存的提交/批准/拒绝/过期竞态测试 |
| Test | 迁移脚本对应测试 | 并查集回填正确性 |
| 前端 | `nodeskclaw-portal/src/views/GeneMarket.vue` | 上传目标选择器移除 org/public 选项（只保留个人库）；覆盖确认弹窗新增版本号输入框（预填 +1 patch 建议值）；fork 覆盖入口透传 `overwrite`，命中 org/public 时提示"已提交等待审核"而不是"覆盖成功" |
| 前端 | 管理员审核队列页面 | 合并展示两类待审核记录，`kind="overwrite"` 的条目展示"将替换：X v1.0.0 → v1.1.0" |
| 前端 | 个人库列表卡片组件 | 读取 `newer_sibling_versions`，按组织名/版本号展示角标；组织库/公共市场的卡片不展示这个字段（后端对这两种 scope 恒返回空数组，前端也不需要为它们渲染角标位置），具体 UI 落地时再定 |

