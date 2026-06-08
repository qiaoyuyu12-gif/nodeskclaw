# MOM Cloud 数据库建表规范

> 所有业务表必须包含以下公共字段，字段顺序建议放在表定义末尾（业务字段之后）。

---

## 一、公共字段规范

每张业务表必须添加如下字段：

```sql
`id`               varchar(32)  NOT NULL                COMMENT '主表ID',
`org_id`           varchar(32)  DEFAULT NULL             COMMENT '组织ID',
`org_name`         varchar(100) DEFAULT NULL             COMMENT '组织名称',
`org_code`         varchar(100) DEFAULT NULL             COMMENT '组织编码',
`del_flag`         char(1)      DEFAULT '0'              COMMENT '删除标志(0正常,1删除)',
`creation_date`    datetime     DEFAULT NULL             COMMENT '创建时间',
`last_update_date` datetime     DEFAULT NULL             COMMENT '最后更新时间',
`created_by`       varchar(50)  DEFAULT NULL             COMMENT '创建人',
`last_updated_by`  varchar(50)  DEFAULT NULL             COMMENT '修改人',
```

---

## 二、建表模板

```sql
CREATE TABLE `xxx_table_name` (
  -- ========== 业务字段 ==========
  `business_field_1` varchar(100) NOT NULL COMMENT '业务字段1',
  `business_field_2` int          DEFAULT 0 COMMENT '业务字段2',
  -- ========== 公共字段（必填，不可省略）==========
  `id`               varchar(32)  NOT NULL                COMMENT '主表ID',
  `org_id`           varchar(32)  DEFAULT NULL             COMMENT '组织ID',
  `org_name`         varchar(100) DEFAULT NULL             COMMENT '组织名称',
  `org_code`         varchar(100) DEFAULT NULL             COMMENT '组织编码',
  `del_flag`         char(1)      DEFAULT '0'              COMMENT '删除标志(0正常,1删除)',
  `creation_date`    datetime     DEFAULT NULL             COMMENT '创建时间',
  `last_update_date` datetime     DEFAULT NULL             COMMENT '最后更新时间',
  `created_by`       varchar(50)  DEFAULT NULL             COMMENT '创建人',
  `last_updated_by`  varchar(50)  DEFAULT NULL             COMMENT '修改人',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='表说明';
```

---

## 三、字段说明

| 字段名                | 类型          | 默认值 | 说明                     |
|--------------------|---------------|--------|------------------------|
| `id`               | varchar(32)   | 无     | 主键，由应用层生成（UUID/雪花）     |
| `org_id`           | varchar(32)   | NULL   | 组织ID，对应 sys_org.org_id |
| `org_name`         | varchar(100)  | NULL   | 组织名称（冗余，避免关联查询）        |
| `org_code`         | varchar(100)  | NULL   | 组织编码（冗余，避免关联查询）        |
| `del_flag`         | char(1)       | '0'    | 逻辑删除：0=正常，1=已删除        |
| `creation_date`    | datetime      | NULL   | 记录创建时间，由框架自动填充         |
| `last_update_date` | datetime      | NULL   | 最后更新时间，由框架自动填充         |
| `created_by`       | varchar(50)   | NULL   | 创建人账号，由框架自动填充          |
| `last_updated_by`  | varchar(50)   | NULL   | 最后修改人账号，由框架自动填充        |

---

## 四、对应 Entity 规范

实体类字段映射（MyBatis-Plus 驼峰自动转换）：

```java
@Data
@TableName("xxx_table_name")
public class XxxEntity {

    // 业务字段 ...

    /** 主表ID */
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    /** 组织ID */
    private String orgId;

    /** 组织名称 */
    private String orgName;

    /** 组织编码 */
    private String orgName;

    /** 删除标志(0正常,1删除) */
    @TableLogic
    private String delFlag;

    /** 创建时间 */
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime creationDate;

    /** 最后更新时间 */
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime lastUpdateDate;

    /** 创建人 */
    @TableField(fill = FieldFill.INSERT)
    private String createdBy;

    /** 修改人 */
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private String lastUpdatedBy;
}
```

---

## 五、MetaObjectHandler 自动填充

框架在 `MomMetaObjectHandler` 中自动填充以下字段，**无需手动赋值**：

| 操作   | 自动填充字段                                                                                        |
|--------|-----------------------------------------------------------------------------------------------|
| INSERT | `creationDate`, `lastUpdateDate`, `createdBy`, `lastUpdatedBy`, `orgId`, `orgCode`, `orgName` |
| UPDATE | `lastUpdateDate`, `lastUpdatedBy`                                                             |

---

## 六、注意事项

1. `id` 使用 `varchar(32)` + `IdType.ASSIGN_UUID`，不使用自增整数。
2. `org_id` 存储 `sys_org.id`, `org_code` 存储业务编码，如 `A101`。
3. `del_flag` 配合全局逻辑删除配置（`application.yml: logic-delete-field: del_flag`），查询自动过滤已删除记录。
4. 日期字段使用 `datetime` 类型，对应 Java `LocalDateTime`，序列化格式 `yyyy-MM-dd HH:mm:ss`。
5. 禁止手动维护 `creation_date`、`last_update_date`、`created_by`、`last_updated_by`，统一由 `MomMetaObjectHandler` 处理。
