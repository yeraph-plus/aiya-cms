"""Error codes and IntegrityError wrapping for the db component (spec §9)."""

from sqlalchemy.exc import IntegrityError

from inc.kernel.errors import AppError, ErrorCode

DB_001 = ErrorCode("DB_001", 500, "数据库连接失败")
DB_002 = ErrorCode("DB_002", 409, "数据冲突(唯一约束违例等)")

DB_CODES: tuple[ErrorCode, ...] = (DB_001, DB_002)


def integrity_to_app_error(exc: IntegrityError) -> AppError:
    """Wrap a SQLAlchemy :class:`IntegrityError` as :data:`DB_002` (spec §9)."""
    return AppError(DB_002, cause=exc)
