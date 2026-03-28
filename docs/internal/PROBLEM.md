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
