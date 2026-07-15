# Importing this package registers every model on Base.metadata
# (alembic autogenerate and relationship resolution rely on it).
from app.models.auth_token import AuthToken
from app.models.user import User

__all__ = ["AuthToken", "User"]
