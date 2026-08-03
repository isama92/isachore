from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chore import Chore
    from app.models.tag import Tag
    from app.models.user import User


class HouseholdRole(StrEnum):
    """What a member may do inside one household. A ladder, not a set of flags:
    organiser > deputy > helper, and `app.core.households.roles_at_least` is the
    only place that ordering is written down.

    organiser manages the household's chores and tags on top of everything a
    deputy can do; deputy adds History and Statistics to what a helper can do;
    helper can only tick chores off. Household *ownership* stays a separate fact
    (`Household.admin_id`) and outranks all three: the owner is always an
    organiser, and only they rename or delete the household, remove members or
    transfer it. Setting roles and inviting are organiser-level, with one
    asymmetry - an organiser may not grant `organiser` or change a row that
    already holds it, so only the owner can grow that set.
    """

    organiser = "organiser"
    deputy = "deputy"
    helper = "helper"


# n-m: users belong to one or more households
household_members = Table(
    "household_members",
    Base.metadata,
    Column("household_id", ForeignKey("households.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    # What this member may do here. Stored as a plain String (closed set enforced
    # at the schema layer, same approach as users.status) so a future role needs
    # no migration. The server_default is deliberately the *least* privileged
    # role: this is an association Table, so the `members` relationship inserts
    # only the two foreign keys, and `add_member` is the only path that states a
    # role. Anything that bypasses it therefore fails closed.
    Column("role", String(30), nullable=False, server_default=HouseholdRole.helper),
)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # The household owner: the only member allowed to edit or delete the household, remove
    # members and transfer it (organisers set roles and invite). Always references a current
    # member (see the household endpoints); users are soft-deleted, never hard-deleted, so
    # no cascade.
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Soft delete: NULL means active, a timestamp means the household is deleted
    # and hidden from the user surface (admins can still view and restore it).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
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
