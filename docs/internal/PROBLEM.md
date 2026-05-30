# 常见问题解决方案

## 1. 缺少环境变量配置

**错误信息：**
```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
llm_api_key
  Field required [type=missing, input_value={}, input_type=dict]
jwt_secret_key
  Field required [type=missing, input_value={}, input_type=dict]
```

**原因：** 缺少 `.env` 配置文件

**解决方案：**
```bash
cd backend
cp .env.example .env
```

然后根据需要修改 `.env` 中的配置。

---

## 2. MySQL 连接失败

**错误信息：**
```
pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on 'localhost'")
```

**原因：** `.env` 中 `DATABASE_URL` 配置了 MySQL，但本地没有运行 MySQL 服务

**解决方案（二选一）：**

### 方案 A：改用 SQLite（推荐，无需额外服务）

修改 `backend/.env` 中的 `DATABASE_URL`：
```env
# 原配置（MySQL）
# DATABASE_URL=mysql+aiomysql://apaas:apaas2024@localhost:3306/apaas_builder?charset=utf8mb4

# 改为 SQLite
DATABASE_URL=sqlite+aiosqlite:///./apaas_builder.db
```

### 方案 B：启动 MySQL 服务

1. 安装并启动 MySQL
2. 创建数据库和用户：
```sql
CREATE DATABASE apaas_builder CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'apaas'@'localhost' IDENTIFIED BY 'apaas2024';
GRANT ALL PRIVILEGES ON apaas_builder.* TO 'apaas'@'localhost';
FLUSH PRIVILEGES;
```

---

## 3. 端口被占用

**错误信息：** `Address already in use`

**解决方案：**

修改端口配置：
- 后端：`backend/.env` 中的 `PORT`
- 前端：`frontend/vite.config.ts` 中的 `server.port`

或者杀掉占用端口的进程：
```bash
# 查看占用端口的进程
lsof -i :8000
lsof -i :5173

# 杀掉进程
kill -9 <PID>
```

---

## 4. 关联表单 / 数据选择器落到平台后配置不完整

**现象：**
- `数据单选 / 数据选择` 在平台里没有真正绑定目标表单和目标字段
- `关联表单` 在平台页面里“本表单字段”没有自动选中
- 页面上能看到组件，但内部关联配置是不完整的

**已确认根因：**
- 我们之前只按文档最小结构写了 `dataSelectorConfig` / `formAssociationConfig`
- 平台真正保存页面配置时，还要求一层内部字段
- 这层字段依赖“目标表单 formId”和“目标组件 uuid”，所以不能只在创建表单时一次性写完

**当前确认的正确方向：**
- 所有表单先创建完
- 再统一回写组件引用
- 回写时使用平台详情页真实结构，而不是只用文档最小结构

**组件回写重点字段：**
- 数据选择器：
  - `componentType=FORM_DATA_SELECTOR`
  - `chooseType=SINGLE`
  - `associationField.originUuid`
  - `dataSelector.otherFormId`
  - `dataSelector.otherComponent`
  - `dataSelector.otherComponentType`
  - `dataSelector.displayComponents`
  - `dataSelector.formAssignments`
- 关联表单：
  - `componentType=FORM_ASSOCIATION`
  - `associationFormId`
  - `associationField.originUuid`
  - `associationField.targetUuid`
  - `displayFields`
  - `displayStyle`
  - `quoteViewType`

**验证标准：**
- `客户` 组件在平台详情页里应为数据选择器，而不是普通文本输入
- `关联工单` 组件应自动选中“本表单字段”
- 平台保存组件时不再报“目标表单为空”

---

## 5. 自定义权限已生成，但平台页面仍显示默认权限

**现象：**
- 本地 `config_preview` 里已经有业务权限规则
- `formPermission` 接口也能调用成功
- 但平台页面“页面设置 -> 权限设置”里仍只显示默认权限组

**已确认根因：**
- 平台页面不只读取 `formPermission` 写口结果
- 页面实际还会读取表单详情配置里的：
  - `permissionGroups`
  - `advancedPermissionGroups`
  - `operationPermissionGroups`
- 之前代码只写了权限 API，没有把页面读取的结构一起回写完整

**当前确认的正确方向：**
- 先调用 `formPermission`
- 再回写表单详情页配置中的权限字段
- `permissionGroups` 必须和业务权限同步生成，不能继续保留平台默认的 `ALL_USER`

**验证标准：**
- 平台页面不再只显示“系统提供的默认权限组”
- 业务角色如 `sales_admin / sales_user / finance_user` 能直接显示出来
- 数据范围与查看/编辑/删除/导出等开关和文档一致

### 2026-05-30 实测根因（app_id=26 SRM供应商档案管理 live 验证）

把「设计器→表单→权限」第 5 子 tab 的**写入**端点 (`POST /applications/{id}/forms/{form_id}/permissions`
→ MCP `set_apaas_form_permissions` → `apaas_client.create_form_permissions`
→ `POST /xdap-app/common/resource/formPermission`) 跑通到底，抓到两层真相：

**A. 写端点裸 500 的根因 = 3 段 payload bug（已逐一抓 apaas 响应体 `{"code":"error","message":"JsonError"}` 实证）：**
1. `formCode` 用错——之前拿 `main_model_code`(modelCode) 当 formCode。实测
   `formCode='idm-srm-supplier_file-form'`(横杠式) ≠ `modelCode='idm_srm_supplier_file'`(下划线式)。
   真值在 `get_apaas_form_detail` 走的 `detailPageConfigById` 顶层 `formCode` 字段，直接读，零额外请求。
2. `tenantId: ""` 空串——apaas DTO 里 tenantId 是 `Long`，Jackson 把 `""` 转 Long 抛 → JsonError。
   修：`create_form_permissions` 发请求前用 client 已知真 `tenant_id` 填空（取不到就删 key 走 null，绝不传 `""`）。
3. `permissionObjectType: "ROLE_USER"`——formPermission 写端点 enum 只认 `"ROLE"`（读端也序列化成 ROLE，
   生成时 advancedPermissionGroups 用的也是 ROLE）。`_build_perm_payload_from_simple_rules` 之前把 ROLE→ROLE_USER
   归一是错的，apaas 无此枚举常量 → JsonError。要反向 normalize ROLE_USER→ROLE。

**B. ⚠️ 致命：三段都修好、apaas 返回 ok 之后，写入仍是「破坏性」的——印证本节标题。**
   实测：写"成功"后立即 `list_apaas_form_permissions` 读回 **空矩阵**（原本 3 角色 idm_admin/idm_srm_user/
   idm_readonly_user 全没了）。即 **formPermission 写口存储 ≠ 读口看的 `advancedPermissionGroups`**。
   裸调写口 = 把读端可见的表单权限**清空**。对比同应用没碰过的表单（SRM供应商罚款）3 角色完好 → 实锤是写口干的。
   - 恢复手法（已验证）：把 app status 翻成非 completed → 重跑 `generate-run`，forms 阶段按 SPEC 重写
     formConfigDetail（含 advancedPermissionGroups）即可恢复被清空的权限。
   - 结论：本 session 已把 3 段 payload 修复 + 诊断全部**回退**，写端点维持「失败-安全」(500) 状态，不留
     「能调用但毁数据」的半截代码。**完整修复 = 上述 3 段 payload 修复 + 同时回写 form-detail config 的
     advancedPermissionGroups/operationPermissionGroups/permissionGroups（§5 已指方向）+ §6 的一角色一权限组聚合**，
     下次连同做完整、live 验证读回 3 角色不丢再落地。读端点 (`get_form_permissions` 只读矩阵) 不受影响，PA1-PA4 仍有效。

---

## 6. 权限组已生成，但页面中“权限对象”为空，且同一角色被拆成多个权限组

**现象：**
- 平台页面已经出现了自定义权限组名称
- 但组内没有挂上具体角色/人员，页面显示“添加权限对象”
- 同一个角色被拆成“基础权限 / 扩展权限”两个组，而不是一个角色一个权限组

**当前判断：**
- 我们回写的 `advancedPermissionGroups / operationPermissionGroups / permissionGroups` 结构还不完全符合页面编辑器实际期望
- `permissionObjectType / permissionObjectValue / permissionValue / permissionType` 这几层对象编码可能没有用对
- 当前实现把一个角色拆成了：
  - 基础权限组
  - 扩展权限组
  这和业务预期“一个角色一个权限组”不一致

**业务期望：**
- 一个角色只生成一个权限组
- 权限组下直接显示该角色，不出现空的“添加权限对象”
- 同一个角色的查看/编辑/删除/导出/打印等权限在同一组内聚合展示

**验证标准：**
- 页面中每个角色只看到一个权限组
- 权限组下能直接看到对应角色
- 不再出现“组有了，但组里没人”的情况

**补充确认：**
- 页面展示名称应使用角色名称，如 `销售管理员 / 销售专员 / 财务人员`
- 权限对象值仍应传平台角色编码，如 `R_sales_admin`
- 不能只创建权限组名称，必须把角色对象一起挂进组内

---

## 7. 查看应用页不应再展示“部署进度”侧栏

**现象：**
- 应用已经构建完成
- 但“查看应用”页面右侧仍保留一整块“部署进度”侧栏
- 该区域占用较大空间，影响文档/应用内容查看

**业务期望：**
- “查看应用”是结果查看态，不再展示构建过程侧栏
- 构建进度只在执行构建时展示，不在查看态常驻

**验证标准：**
- 进入“查看应用”页面后，右侧不再显示部署进度面板
- 页面主体宽度恢复给应用说明/文档内容使用

---

## 8. 顶部模式切换区需要缩小，并补充图标

**现象：**
- 顶部 `智能搭建 / 辅助搭建 / 智能开发` 切换区占用宽度偏大
- Tab 目前只有文字和状态点，辨识度不够
- 顶部模式切换区整体收紧，减少横向占用
- 每个 Tab 增加一个小图标，使用 SVG

**已定位文件：**
- [`frontend/src/views/ChatPage.vue`](/Users/admin/Desktop/AI/智能搭建/apaas-builder-ai/frontend/src/views/ChatPage.vue)
- [`frontend/src/components/GlobalNavRail.vue`](/Users/admin/Desktop/AI/智能搭建/apaas-builder-ai/frontend/src/components/GlobalNavRail.vue)

**UI 约束：**
- 继续保持现有浅色、圆角、轻量风格
- 图标尺寸应小且统一，避免喧宾夺主
- 缩小后仍需保证可点击面积和可读性

**验证标准：**
- 顶部模式切换区明显更紧凑
- 三个 Tab 都有统一风格的小 SVG 图标

---

## 9. 数据单选 / 数据选择后置回写会把组件改坏

**现象：**
- 原始创建时组件类型正确
- 后置同步引用后，平台里组件表现异常，甚至被改成不符合预期的展示结构

**当前修复方向：**
- 数据单选 / 数据选择先回退到“仅用创建表单时的原始 payload”
- 暂时停止对数据选择器做后置回写
- 关联表单仍单独保留后置回写能力

**验证标准：**
- `客户` 组件恢复为数据选择器，而不是表格/关联表单形态
- 数据单选 / 数据选择不再因后置同步发生回归
- 左侧区域能直接看到当前应用名称
