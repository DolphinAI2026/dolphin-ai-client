from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.routes import auth, conversations, chat, applications, apaas, generation_steps, coding, incremental_update, projects, marketplace


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    await init_db()

    # 运行种子数据
    from app.seed_data import seed_initial_data
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    yield
    # 关闭时清理资源


app = FastAPI(
    title="aPaaS Builder AI",
    description="得帆云低代码平台智能搭建 & Vibe Coding 助手",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(apaas.router, prefix="/api")
app.include_router(generation_steps.router, prefix="/api")
app.include_router(coding.router, prefix="/api")
app.include_router(incremental_update.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(marketplace.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
