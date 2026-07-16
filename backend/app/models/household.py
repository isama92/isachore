from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore import Chore
    from app.models.tag import Tag
    from app.models.user import User


# n-m: users belong to one or more households
household_members = Table(
    "household_members",
    Base.metadata,
    Column("household_id", ForeignKey("households.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    members: Mapped[list["User"]] = relationship(
        secondary=household_members, back_populates="households"
    )
    chores: Mapped[list["Chore"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
