from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    voice_settings = relationship(
        "UserVoiceSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserVoiceSettings(Base):
    __tablename__ = "user_voice_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_voice_settings_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    voice_engine: Mapped[str] = mapped_column(String(32), default="kokoro")
    voice_name: Mapped[str] = mapped_column(String(64), default="af_heart")
    language: Mapped[str] = mapped_column(String(16), default="en")
    speaking_speed: Mapped[float] = mapped_column(Float, default=1.0)

    user = relationship("User", back_populates="voice_settings")
