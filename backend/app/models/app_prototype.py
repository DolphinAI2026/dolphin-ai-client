from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AppPrototype(Base):
    """AI Coding 主工作台生成的 HTML 原型快照（app 中心、可版本化）。"""
    __tablename__ = "app_prototypes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_spec_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
