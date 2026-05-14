# 企业级制造执行平台 — 设计文档

> 版本：v1.0  
> 日期：2026-05-09  
> 状态：草稿

## 概述

在 DeskClaw 基础上扩展企业级制造执行平台，支持 Skill 管理、Workflow 工作流编排、Agent 任务执行、RAGFlow 知识库集成、MES/APS 数据层接入。

**目标用户**：制造企业工人/工程师（50-500 人规模）  
**技术方案**：模块化单体（FastAPI + Vue 3 + PostgreSQL）  
**工期估算**：约 11-17 周

---

## 一、系统架构

### 1.1 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                      Frontend (Vue 3)                       │
│   Skill管理 │ Workflow画布 │ Agent监控 │ 知识库 │ MES/APS看板  │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼───────────────────────────────────┐
│                   API Gateway (FastAPI)                       │
│  /api/v1/skills  /api/v1/workflows  /api/v1/agents          │
│  /api/v1/mes  /api/v1/aps  /api/v1/ragflow                   │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│              Modules (Python Package)                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │  Skill  │ │Workflow │ │  Agent  │ │   MES   │ │   APS   │  │
│  │ Manager │ │  Engine │ │Runtime  │ │Adapter  │ │Adapter  │  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘  │
│       │           │           │           │           │       │
│  ┌────▼───────────▼───────────▼───────────▼───────────▼────┐  │
│  │              Shared Services Layer                     │  │
│  │  Auth │ Org │ LLM Proxy │ Storage │ Notification        │  │
│  └────┬──────────────────────────────────────────────────┘  │
│       │                                                        │
│  ┌────▼────┐                                                  │
│  │PostgreSQL│  skill_schema / workflow_schema / agent_schema   │
│  └─────────┘                                                  │
└──────────────────────────────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │ RAGFlow  │  │   MES    │  │   APS   │
      │  API     │  │   API    │  │   API   │
      └──────────┘  └──────────┘  └──────────┘
```

### 1.2 模块职责

| 模块 | 路径 | 职责 |
|------|------|------|
| Skill Manager | `app/modules/skill/` | Skill CRUD、版本管理、执行记录 |
| Workflow Engine | `app/modules/workflow/` | DAG 定义存储、节点执行、状态机 |
| Agent Runtime | `app/modules/agent/` | 任务调度、LLM 调用、流式输出 |
| MES Adapter | `app/modules/mes/` | MES API 适配、数据映射 |
| APS Adapter | `app/modules/aps/` | APS API 适配、数据映射 |
| RAGFlow Gateway | `app/modules/ragflow/` | 知识库管理、文档检索 |

---

## 二、数据模型

### 2.1 数据库 Schema 隔离

```sql
CREATE SCHEMA IF NOT EXISTS skill_schema;
CREATE SCHEMA IF NOT EXISTS workflow_schema;
CREATE SCHEMA IF NOT EXISTS agent_schema;
CREATE SCHEMA IF NOT EXISTS mes_schema;
CREATE SCHEMA IF NOT EXISTS aps_schema;
```

### 2.2 Skill 模块

```python
class Skill(Base):
    """技能定义"""
    __tablename__ = "skills"
    
    id: UUID
    org_id: UUID
    name: str              # 技能名称
    description: str
    version: int
    skill_type: str        # "retrieval" | "action" | "analysis"
    
    definition: dict       # { prompt_template, input_schema, output_schema, llm_config }
    entry_point: str
    ragflow_kb_id: UUID | None
    trigger_config: dict   # { type: "manual"|"scheduled"|"event", config: {} }
    
    status: str            # "draft" | "published" | "archived"
    is_active: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime

class SkillVersion(Base):
    """技能版本历史"""
    __tablename__ = "skill_versions"
    id, skill_id, version, definition, changelog, created_at

class SkillExecution(Base):
    """技能执行记录"""
    __tablename__ = "skill_executions"
    id, skill_id, task_id, user_id, input_params, output_result, error_message
    status: str            # "pending" | "running" | "completed" | "failed"
    started_at, completed_at
```

### 2.3 Workflow 模块

```python
class WorkflowDefinition(Base):
    """工作流定义（DAG）"""
    __tablename__ = "workflow_definitions"
    
    id: UUID
    org_id: UUID
    name: str
    description: str
    version: int
    
    graph: dict            # { "nodes": [...], "edges": [...] }
    entry_node_id: str
    variables: dict        # { name: { type, required, default } }
    
    status: str            # "draft" | "published" | "archived"
    created_by: UUID
    created_at: datetime
    updated_at: datetime

class WorkflowInstance(Base):
    """工作流实例"""
    __tablename__ = "workflow_instances"
    
    id: UUID
    definition_id: UUID
    org_id: UUID
    variables: dict
    status: str            # "pending" | "running" | "paused" | "completed" | "failed" | "cancelled"
    current_node_id: str | None
    node_states: dict      # { node_id: { status, output, error, started_at, completed_at } }
    
    trigger_type: str      # "manual" | "scheduled" | "event" | "api"
    triggered_by: UUID
    
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

class WorkflowNodeExecution(Base):
    """节点执行日志"""
    __tablename__ = "workflow_node_executions"
    id, instance_id, node_id, node_type, input_data, output_data, error
    status, retry_count, started_at, completed_at
```

### 2.4 Agent 模块

```python
class AgentTask(Base):
    """Agent 任务"""
    __tablename__ = "agent_tasks"
    
    id: UUID
    org_id: UUID
    name: str
    description: str
    task_type: str          # "single_skill" | "workflow" | "multi_agent"
    
    config: dict            # { skills, llm_config, max_steps, timeout }
    input: dict
    output: dict | None
    error: str | None
    
    status: str            # "pending" | "planning" | "executing" | "completed" | "failed" | "cancelled"
    execution_plan: list | None  # [{ step, skill_id, input, output }, ...]
    
    workflow_instance_id: UUID | None
    created_by: UUID
    
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

class AgentMessage(Base):
    """Agent 消息/对话记录"""
    __tablename__ = "agent_messages"
    id, task_id, role: str, content, metadata: dict, created_at
```

### 2.5 MES 模块

```python
class MesConnection(Base):
    """MES 连接配置"""
    __tablename__ = "mes_connections"
    
    id: UUID
    org_id: UUID
    name: str
    mes_type: str          # "rest_api" | "soap" | "database"
    config: dict           # { base_url, auth_type, api_key, endpoints, timeout }
    credentials: dict      # 加密存储
    is_active: bool
    last_health_check: datetime | None
    created_at: datetime
    updated_at: datetime

class MesDataMapping(Base):
    """MES 数据字段映射"""
    __tablename__ = "mes_data_mappings"
    
    id: UUID
    org_id: UUID
    mes_connection_id: UUID
    entity_type: str       # "work_order" | "production_report" | "quality_check" | "material_stock"
    field_mappings: dict   # { local_field: mes_api_field }
    filter_rules: dict
    created_at: datetime
    updated_at: datetime
```

### 2.6 APS 模块

```python
class ApsConnection(Base):
    """APS 连接配置"""
    __tablename__ = "aps_connections"
    
    id: UUID
    org_id: UUID
    name: str
    config: dict
    credentials: dict      # 加密存储
    is_active: bool
    last_health_check: datetime | None
    created_at: datetime
    updated_at: datetime

class ApsDataMapping(Base):
    """APS 数据映射"""
    __tablename__ = "aps_data_mappings"
    
    id: UUID
    org_id: UUID
    aps_connection_id: UUID
    data_type: str         # "schedule_result" | "material_plan" | "capacity_plan"
    field_mappings: dict
    filter_rules: dict
    created_at: datetime
    updated_at: datetime
```

---

## 三、API 接口

### 3.1 Skill API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/skills | 创建 Skill |
| GET | /api/v1/skills | 列表（分页、搜索、过滤） |
| GET | /api/v1/skills/{id} | 详情 |
| PUT | /api/v1/skills/{id} | 更新 |
| DELETE | /api/v1/skills/{id} | 删除（软删除） |
| POST | /api/v1/skills/{id}/publish | 发布 |
| POST | /api/v1/skills/{id}/versions | 创建新版本 |
| GET | /api/v1/skills/{id}/versions | 版本历史 |
| POST | /api/v1/skills/{id}/execute | 执行 Skill |
| GET | /api/v1/skills/{id}/executions | 执行记录 |

### 3.2 Workflow API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/workflows | 创建 Workflow |
| GET | /api/v1/workflows | 列表 |
| GET | /api/v1/workflows/{id} | 详情（含 graph） |
| PUT | /api/v1/workflows/{id} | 更新 |
| DELETE | /api/v1/workflows/{id} | 删除 |
| POST | /api/v1/workflows/{id}/publish | 发布 |
| POST | /api/v1/workflows/{id}/instances | 启动实例 |
| GET | /api/v1/workflows/instances/{instance_id} | 实例详情 |
| POST | /api/v1/workflows/instances/{instance_id}/pause | 暂停 |
| POST | /api/v1/workflows/instances/{instance_id}/resume | 恢复 |
| POST | /api/v1/workflows/instances/{instance_id}/cancel | 取消 |

### 3.3 Agent API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/agents/tasks | 创建并启动任务 |
| GET | /api/v1/agents/tasks | 任务列表 |
| GET | /api/v1/agents/tasks/{id} | 任务详情（含执行计划） |
| POST | /api/v1/agents/tasks/{id}/cancel | 取消任务 |
| POST | /api/v1/agents/tasks/{id}/retry | 重试 |
| GET | /api/v1/agents/tasks/{id}/messages | 消息历史 |
| WS | /api/v1/agents/tasks/{id}/stream | WebSocket 流式输出 |

### 3.4 MES API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /api/v1/mes/connections | 连接列表/创建 |
| GET/PUT/DELETE | /api/v1/mes/connections/{id} | 连接详情/更新/删除 |
| POST | /api/v1/mes/connections/{id}/health-check | 健康检查 |
| GET | /api/v1/mes/{connection_id}/work-orders | 工单列表 |
| GET | /api/v1/mes/{connection_id}/work-orders/{order_id} | 工单详情 |
| POST | /api/v1/mes/{connection_id}/production-report | 报工 |
| GET | /api/v1/mes/{connection_id}/quality-checks | 质检记录 |
| POST | /api/v1/mes/{connection_id}/quality-check | 提交质检 |

### 3.5 APS API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /api/v1/aps/connections | 连接列表/创建 |
| GET/PUT/DELETE | /api/v1/aps/connections/{id} | 连接详情/更新/删除 |
| POST | /api/v1/aps/connections/{id}/health-check | 健康检查 |
| GET | /api/v1/aps/{connection_id}/schedules | 排程结果 |
| GET | /api/v1/aps/{connection_id}/materials | 物料计划 |
| GET | /api/v1/aps/{connection_id}/capacity | 产能规划 |

### 3.6 RAGFlow API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | /api/v1/ragflow/knowledge-bases | 知识库列表/创建 |
| GET/PUT/DELETE | /api/v1/ragflow/knowledge-bases/{id} | 知识库详情/更新/删除 |
| POST | /api/v1/ragflow/knowledge-bases/{id}/documents | 上传文档 |
| GET | /api/v1/ragflow/knowledge-bases/{id}/documents | 文档列表 |
| DELETE | /api/v1/ragflow/documents/{id} | 删除文档 |
| POST | /api/v1/ragflow/retrieval | 检索（Skill 触发） |

---

## 四、前端页面

### 4.1 导航结构

```
顶部导航栏
├── Logo + 平台名称
├── 主导航：
│   ├── 控制台（Dashboard）
│   ├── 技能市场（Skill 管理）
│   ├── 工作流（Workflow 管理）
│   ├── 任务中心（Agent 执行）
│   ├── 知识库（RAGFlow）
│   ├── MES 数据（数据看板）
│   └── APS 数据（排程结果）
├── 组织切换器
└── 用户菜单
```

### 4.2 页面清单

| 页面 | 路由 | 说明 |
|------|------|------|
| 控制台 | `/` | 生产概览、待办任务、快捷入口 |
| 技能市场 | `/skills` | 技能列表、详情、版本管理 |
| 技能编辑 | `/skills/:id/edit` | 可视化技能定义编辑器 |
| 工作流列表 | `/workflows` | 工作流定义列表 |
| 工作流画布 | `/workflows/:id/canvas` | DAG 可视化编辑器 |
| 工作流实例 | `/workflows/instances/:id` | 实例执行详情、节点状态 |
| 任务中心 | `/agents/tasks` | 任务列表、流式输出 |
| 知识库 | `/knowledge-bases` | RAGFlow 知识库管理 |
| MES 连接 | `/mes/connections` | MES API 配置、健康检查 |
| MES 数据 | `/mes/data` | 工单、报工、质检数据 |
| APS 连接 | `/aps/connections` | APS API 配置 |
| APS 数据 | `/aps/schedules` | 排程结果展示 |

### 4.3 组件结构

```
src/components/skill/
├── SkillEditor.vue          # 主编辑器容器
├── SkillBasicInfo.vue       # 基本信息表单
├── SkillPromptEditor.vue    # Prompt 模板编辑器
├── SkillInputSchema.vue     # 输入参数定义
├── SkillOutputSchema.vue    # 输出结构定义
├── SkillTriggerConfig.vue   # 触发配置
├── SkillTestPanel.vue       # 测试面板
└── useSkillEditor.ts        # 编辑器逻辑 composable

src/components/workflow/
├── WorkflowCanvas.vue         # 主画布容器
├── canvas/
│   ├── CanvasView.vue         # 画布视图（Pan/Zoom）
│   ├── CanvasGrid.vue         # 网格背景
│   └── SelectionBox.vue       # 选择框
├── nodes/
│   ├── BaseNode.vue           # 节点基础组件
│   ├── StartNode.vue          # 开始节点
│   ├── EndNode.vue            # 结束节点
│   ├── SkillNode.vue          # Skill 节点
│   ├── MesActionNode.vue      # MES 操作节点
│   ├── ConditionNode.vue      # 条件分支节点
│   └── TransformNode.vue      # 数据转换节点
├── edges/
│   ├── BaseEdge.vue           # 边基础组件
│   ├── ConditionalEdge.vue   # 条件边
│   └── EdgeAnchors.vue        # 连接点
├── panels/
│   ├── NodeConfigPanel.vue    # 节点配置面板
│   ├── VariablePanel.vue      # 变量面板
│   └── CanvasToolbar.vue      # 画布工具栏
└── useWorkflowCanvas.ts       # 画布逻辑 composable
```

---

## 五、后端实现

### 5.1 MES 适配器

#### 适配器基类

```python
# app/modules/mes/adapters/base.py
class MesAdapter(ABC):
    @abstractmethod
    async def get_work_orders(self, filters: dict) -> list[dict]: pass
    
    @abstractmethod
    async def get_work_order(self, order_id: str) -> dict: pass
    
    @abstractmethod
    async def report_production(self, order_id: str, data: dict) -> dict: pass
    
    @abstractmethod
    async def submit_quality_check(self, order_id: str, data: dict) -> dict: pass
    
    @abstractmethod
    async def health_check(self) -> bool: pass
```

#### REST 适配器

```python
# app/modules/mes/adapters/rest_adapter.py
class RestMesAdapter(MesAdapter):
    def __init__(self, config: dict):
        self.base_url = config["base_url"].rstrip("/")
        self.api_key = config.get("api_key")
        self.timeout = config.get("timeout", 30)
        self.endpoints = config.get("endpoints", {
            "work_orders": "/api/work-orders",
            "production_report": "/api/production/report",
            "quality_check": "/api/quality/check"
        })
    
    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method, f"{self.base_url}{path}",
                headers=self._auth_headers(), **kwargs
            )
            response.raise_for_status()
            return response.json()
    
    async def get_work_orders(self, filters: dict) -> list[dict]:
        response = await self._request("GET", self.endpoints["work_orders"], params=filters)
        return response.get("data", [])
    
    async def report_production(self, order_id: str, data: dict) -> dict:
        response = await self._request("POST", self.endpoints["production_report"],
            json={"work_order_id": order_id, **data})
        return response.get("data", {})
```

#### 适配器注册与工厂

```python
# app/modules/mes/adapters/registry.py
class MesAdapterRegistry:
    _adapters: dict[str, type[MesAdapter]] = {}
    
    @classmethod
    def register(cls, mes_type: str, adapter_class: type[MesAdapter]):
        cls._adapters[mes_type] = adapter_class
    
    @classmethod
    def create(cls, mes_type: str, config: dict) -> MesAdapter:
        return cls._adapters[mes_type](config)

MesAdapterRegistry.register("rest_api", RestMesAdapter)
```

#### 统一服务接口

```python
# app/modules/mes/service.py
class MesService:
    def __init__(self, org_id: UUID):
        self.org_id = org_id
        self._adapters: dict[UUID, MesAdapter] = {}
        self._mappers: dict[str, MesDataMapper] = {}
    
    async def get_adapter(self, connection_id: UUID) -> MesAdapter:
        if connection_id not in self._adapters:
            conn = await self._load_connection(connection_id)
            self._adapters[connection_id] = MesAdapterRegistry.create(conn.mes_type, conn.config)
        return self._adapters[connection_id]
    
    async def get_work_orders(self, connection_id: UUID, **filters) -> list[dict]:
        adapter = await self.get_adapter(connection_id)
        mapper = await self.get_mapper(connection_id, "work_order")
        data = await adapter.get_work_orders(filters)
        return [mapper.map_to_local(item, "work_order") for item in data]
    
    async def report_production(self, connection_id: UUID, order_id: str, **data) -> dict:
        adapter = await self.get_adapter(connection_id)
        mapper = await self.get_mapper(connection_id, "production_report")
        mes_data = mapper.map_to_mes(data, "production_report")
        result = await adapter.report_production(order_id, mes_data)
        return mapper.map_to_local(result, "production_report")
```

### 5.2 Skill 执行引擎

#### Skill 定义解析

```python
# app/modules/skill/engine/definition.py
class SkillDefinition(BaseModel):
    prompt_template: str
    input_schema: dict[str, SkillParameter]
    output_schema: SkillOutputSchema
    llm_config: dict[str, Any] = {}
    
    def render_prompt(self, variables: dict[str, Any]) -> str:
        prompt = self.prompt_template
        for key, value in variables.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(value))
        return prompt
    
    def validate_input(self, inputs: dict[str, Any]) -> list[str]:
        errors = []
        for name, param in self.input_schema.items():
            value = inputs.get(name)
            if param.required and value is None:
                errors.append(f"Missing required parameter: {name}")
        return errors
```

#### Skill 执行器

```python
# app/modules/skill/engine/executor.py
class SkillExecutor:
    def __init__(self, org_id: UUID, llm_proxy_url: str, ragflow_adapter=None):
        self.org_id = org_id
        self.llm_proxy_url = llm_proxy_url
        self.ragflow_adapter = ragflow_adapter
    
    async def execute(self, skill_id: UUID, inputs: dict, task_id: UUID = None) -> dict:
        # 1. 加载 Skill 定义
        skill = await self._load_skill(skill_id)
        definition = SkillDefinition(**skill.definition)
        
        # 2. 验证输入
        errors = definition.validate_input(inputs)
        if errors:
            raise SkillValidationError("\n".join(errors))
        
        # 3. 获取 RAGFlow 知识库上下文
        rag_context = None
        if skill.ragflow_kb_id:
            query = definition.render_prompt(inputs)
            rag_context = await self._retrieve_knowledge(skill.ragflow_kb_id, query)
        
        # 4. 构建并调用 LLM
        llm_request = await self._build_llm_request(skill, inputs, rag_context)
        llm_response = await self._call_llm(llm_request)
        
        # 5. 解析输出并记录
        output = self._parse_output(llm_response, definition.output_schema)
        await self._log_execution(skill_id, task_id, inputs, output)
        
        return output
    
    def _build_system_prompt(self, skill, rag_context):
        parts = [f"你是一个专业的 {skill.name} 助手。", f"技能描述：{skill.description}", ""]
        if rag_context:
            parts.append("## 知识库参考信息：")
            for i, item in enumerate(rag_context, 1):
                parts.append(f"\n[{i}] {item.get('content', '')}")
        return "\n".join(parts)
```

### 5.3 Workflow DAG 引擎

#### 节点基类

```python
# app/modules/workflow/engine/nodes/base.py
class NodeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"

@dataclass
class NodeContext:
    instance_id: UUID
    node_id: str
    variables: dict
    node_states: dict
    adapter_registry: dict

@dataclass
class NodeResult:
    output: dict | None = None
    error: str | None = None
    status: NodeStatus = NodeStatus.PENDING

class WorkflowNode(ABC):
    def __init__(self, node_id: str, config: dict):
        self.node_id = node_id
        self.config = config
    
    @property
    @abstractmethod
    def node_type(self) -> str: pass
    
    @abstractmethod
    async def execute(self, ctx: NodeContext) -> NodeResult: pass
```

#### 内置节点类型

```python
class StartNode(WorkflowNode):
    node_type = "start"
    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output={"started": True}, status=NodeStatus.COMPLETED)

class EndNode(WorkflowNode):
    node_type = "end"
    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output={"ended": True}, status=NodeStatus.COMPLETED)

class SkillNode(WorkflowNode):
    node_type = "skill"
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        skill_id = self.config["skill_id"]
        inputs = self._resolve_inputs(self.config.get("inputs", {}))
        
        skill_service = ctx.adapter_registry["skill"]
        try:
            result = await skill_service.execute(skill_id, inputs, ctx.instance_id)
            return NodeResult(output=result, status=NodeStatus.COMPLETED)
        except Exception as e:
            return NodeResult(error=str(e), status=NodeStatus.FAILED)

class MesActionNode(WorkflowNode):
    node_type = "mes_action"
    
    async def execute(self, ctx: NodeContext) -> NodeResult:
        mes_conn_id = self.config["mes_connection_id"]
        action = self.config["action"]
        params = self._resolve_inputs(self.config.get("params", {}))
        
        mes_service = ctx.adapter_registry["mes"]
        try:
            result = await mes_service.execute_action(mes_conn_id, action, params)
            return NodeResult(output=result, status=NodeStatus.COMPLETED)
        except Exception as e:
            return NodeResult(error=str(e), status=NodeStatus.FAILED)
```

#### DAG 执行器

```python
# app/modules/workflow/engine/executor.py
class WorkflowExecutor:
    def __init__(self, instance_id: UUID, definition: dict, ctx: NodeContext):
        self.instance_id = instance_id
        self.definition = definition
        self.ctx = ctx
        self.graph = definition["graph"]
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.edges = self.graph["edges"]
        
        self.node_registry: dict[str, type[WorkflowNode]] = {
            "start": StartNode, "end": EndNode,
            "skill": SkillNode, "mes_action": MesActionNode,
            "condition": ConditionNode,
        }
    
    async def execute(self):
        entry_node_id = self.definition["entry_node_id"]
        await self._execute_node(entry_node_id)
        
        while not self._is_terminated():
            await asyncio.sleep(0.1)
        
        return self.ctx.node_states
    
    async def _execute_node(self, node_id: str):
        node_def = self.nodes[node_id]
        
        if not await self._can_execute(node_id):
            self.ctx.node_states[node_id] = {"status": NodeStatus.WAITING.value}
            return
        
        node_class = self.node_registry.get(node_def["type"])
        node = node_class(node_id, node_def.get("config", {}))
        
        self.ctx.node_states[node_id] = {
            "status": NodeStatus.RUNNING.value,
            "started_at": datetime.utcnow().isoformat()
        }
        await self._save_instance_state()
        
        result = await node.execute(self.ctx)
        
        self.ctx.node_states[node_id].update({
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "completed_at": datetime.utcnow().isoformat()
        })
        await self._save_instance_state()
        
        if result.status == NodeStatus.COMPLETED:
            for next_id in node.get_next_nodes(self.edges):
                await self._execute_node(next_id)
    
    async def _can_execute(self, node_id: str) -> bool:
        predecessors = [e["source"] for e in self.edges if e["target"] == node_id]
        for pred_id in predecessors:
            state = self.ctx.node_states.get(pred_id, {})
            if state.get("status") not in [NodeStatus.COMPLETED.value, NodeStatus.SKIPPED.value]:
                return False
        return True
    
    def _is_terminated(self) -> bool:
        for node_def in self.nodes.values():
            if node_def["type"] == "end":
                end_state = self.ctx.node_states.get(node_def["id"], {})
                if end_state.get("status") != NodeStatus.COMPLETED.value:
                    return False
        return True
```

---

## 六、Implementation Plan

### Phase 1: 基础设施（1-2 周）
- [ ] 创建模块目录结构 `app/modules/{skill,workflow,agent,mes,aps,ragflow}/`
- [ ] 定义数据库 Schema 迁移
- [ ] 实现适配器基类和注册表
- [ ] 配置 FeatureGate 新功能开关

### Phase 2: Skill 模块（2-3 周）
- [ ] Skill CRUD API
- [ ] Skill 版本管理
- [ ] Skill 执行引擎
- [ ] Skill 触发器（手动/定时/事件）
- [ ] 前端 Skill 管理页面
- [ ] Skill 编辑器组件

### Phase 3: Workflow 模块（3-4 周）
- [ ] Workflow 定义存储
- [ ] DAG 引擎实现
- [ ] 内置节点类型（Start/End/Skill/MES Action/Condition）
- [ ] 工作流状态持久化
- [ ] 错误处理与重试
- [ ] 前端 Workflow 画布
- [ ] 节点配置面板

### Phase 4: Agent 模块（2-3 周）
- [ ] 任务创建与调度
- [ ] LLM 集成
- [ ] Multi-Skill 编排
- [ ] 流式输出（WebSocket）
- [ ] 前端任务中心

### Phase 5: MES/APS 集成（2-3 周）
- [ ] MES REST 适配器
- [ ] APS REST 适配器
- [ ] 数据映射配置
- [ ] 前端 MES/APS 数据看板

### Phase 6: RAGFlow 集成（1-2 周）
- [ ] RAGFlow 适配器
- [ ] 知识库管理
- [ ] Skill 知识库绑定
- [ ] 前端知识库页面

---

## 七、技术栈

| 层级 | 技术 |
|------|------|
| 前端框架 | Vue 3 + Tailwind CSS + shadcn-vue |
| 画布组件 | @vue-flow/core |
| 后端框架 | FastAPI + SQLAlchemy + asyncpg |
| 任务队列 | FastAPI BackgroundTasks / Celery |
| 数据库 | PostgreSQL |
| LLM | LLM Proxy（兼容 OpenAI 格式） |
| 工作流引擎 | 自研 DAG（轻量级） |
| 部署 | Docker Compose |

---

## 八、决策记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-05-09 | 模块化单体架构 | 团队规模中等（50-500用户），快速落地，无需微服务复杂度 |
| 2026-05-09 | 自研 DAG 引擎 | 轻量级需求，无需 Temporal 等重量级框架 |
| 2026-05-09 | REST API 适配器 | MES/APS 均提供 REST API，直接对接 |
| 2026-05-09 | RAGFlow 知识库 | 工艺文档 + 质量标准双用途，Skill 可绑定知识库 |
