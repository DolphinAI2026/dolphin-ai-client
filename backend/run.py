import logging
import uvicorn
from app.config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)

# 确保 apaas_client 模块日志可见
logging.getLogger("app.apaas_client").setLevel(logging.INFO)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info"
    )
