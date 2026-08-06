"""Registration, login, refresh rotation and logout service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from inc.kernel.cache import Cache, cache_key
from inc.kernel.db import UoWExecutor, integrity_to_app_error, new_uuid7
from inc.kernel.errors import AppError
from inc.kernel.events import Event, EventBus, get_event_bus
from inc.kernel.identity.models import Identity, User, UserStatus
from inc.kernel.identity.schemas import UserRead
from inc.kernel.rbac.errors import RBAC_002
from inc.kernel.rbac.models import Role
from inc.kernel.security import (
    AUTH_003,
    Principal,
    PrincipalClaims,
    TokenService,
    hash_password,
    hash_refresh,
    verify_password,
)

from .errors import AUTH_001, AUTH_004, AUTH_005, AUTH_006, AUTH_007, AUTH_008, AUTH_009, AUTH_010
from .events import (
    AUTH_EVENT_TYPES,
    UserLoginFailedPayload,
    UserLoginSucceededPayload,
    UserPasswordChangedPayload,
    UserRegisteredPayload,
)
from .models import PasswordResetToken, RefreshToken
from .schemas import (
    AuthMe,
    AuthRegistrationPolicy,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordResetDelivery,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
)
from .uow import AuthUnitOfWork

_LOGIN_LIMIT = 5
_LOGIN_WINDOW_SECONDS = 300
_RESET_LIMIT = 5
_RESET_WINDOW_SECONDS = 900
_DUMMY_PASSWORD_HASH = hash_password("aiya-invalid-user-password")


class AuthService:
    def __init__(
        self,
        executor: UoWExecutor[AuthUnitOfWork],
        token_service: TokenService,
        cache: Cache,
        *,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._executor = executor
        self.token_service = token_service
        self._cache = cache
        self._event_bus = event_bus or get_event_bus()
        self._clock = clock or (lambda: datetime.now(UTC))
        for event_type in AUTH_EVENT_TYPES:
            if not self._event_bus.is_registered(event_type):
                self._event_bus.register(event_type)

    async def register(
        self,
        dto: RegisterRequest,
        policy: AuthRegistrationPolicy | None = None,
    ) -> UserRead:
        resolved = policy or AuthRegistrationPolicy()
        if not resolved.registration_open:
            raise AppError(AUTH_008)
        return await self._register_with_role(
            dto,
            role_name=resolved.default_role,
            allow_missing_role=False,
        )

    async def bootstrap_admin(self, dto: RegisterRequest) -> UserRead:
        """Create the first administrator without exposing a public HTTP route."""
        return await self._register_with_role(dto, role_name="admin", allow_missing_role=False)

    async def request_password_reset(
        self, dto: ForgotPasswordRequest, *, ip: str = "unknown"
    ) -> PasswordResetDelivery | None:
        rate_key = cache_key("auth", "password_reset", dto.email.strip().lower(), ip)
        attempts = await self._cache.get(rate_key)
        try:
            if int(attempts or 0) >= _RESET_LIMIT:
                raise AppError(AUTH_010)
        except ValueError:
            pass
        await self._cache.increment(rate_key, _RESET_WINDOW_SECONDS)
        raw_token = token_urlsafe(48)
        token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
        now = self._now()
        expires_at = now + timedelta(minutes=30)

        async def operation(uow: AuthUnitOfWork) -> PasswordResetDelivery | None:
            candidate = await uow.auth.find_login_candidate(dto.email)
            if candidate is None:
                return None
            user, _identity = candidate
            await uow.password_reset_tokens.consume_for_user(user.id, now)
            await uow.password_reset_tokens.add(
                PasswordResetToken(
                    id=new_uuid7(),
                    user_id=user.id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
            )
            return PasswordResetDelivery(email=user.email, token=raw_token)

        return await self._executor.write(operation)

    async def reset_password(self, dto: ResetPasswordRequest) -> None:
        token_hash = sha256(dto.token.encode("utf-8")).hexdigest()
        now = self._now()

        async def operation(uow: AuthUnitOfWork) -> UUID:
            row = await uow.password_reset_tokens.get_by_hash_for_update(token_hash)
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                raise AppError(AUTH_009)
            identity = await uow.identities.get_password_for_update(row.user_id)
            if identity is None:
                raise AppError(AUTH_009)
            identity.secret_hash = hash_password(dto.password)
            identity.verified = True
            row.consumed_at = now
            await uow.refresh_tokens.revoke_all_for_user(row.user_id, now)
            return row.user_id

        user_id = await self._executor.write(operation)
        self._publish(
            Event(type="user.password_changed", payload=UserPasswordChangedPayload(user_id=user_id))
        )

    async def _register_with_role(
        self,
        dto: RegisterRequest,
        *,
        role_name: str,
        allow_missing_role: bool,
    ) -> UserRead:
        async def operation(uow: AuthUnitOfWork) -> User:
            email = dto.email.strip().lower()
            if await uow.users.get_by_email(email) is not None:
                raise AppError(AUTH_004)
            if await uow.users.get_by_username(dto.username) is not None:
                raise AppError(AUTH_005)
            role = await uow.roles.get_by_name(role_name)
            if role is None:
                if not allow_missing_role:
                    raise AppError(RBAC_002, detail={"role": role_name})
                role = Role(id=new_uuid7(), name=role_name, description="注册用户")
                await uow.roles.add(role)
            user = User(
                id=new_uuid7(),
                username=dto.username,
                email=email,
                display_name=dto.display_name or dto.username,
            )
            await uow.users.add(user)
            await uow.flush()
            await uow.identities.add(
                Identity(
                    id=new_uuid7(),
                    user_id=user.id,
                    provider="password",
                    provider_uid=email,
                    secret_hash=hash_password(dto.password),
                    verified=False,
                )
            )
            await uow.flush()
            await uow.rbac.assign_role(user.id, role.id)
            return user

        try:
            user = await self._executor.write(operation)
        except IntegrityError as exc:
            raise integrity_to_app_error(exc) from exc
        result = UserRead.model_validate(user)
        self._publish(
            Event(type="user.registered", payload=UserRegisteredPayload(user_id=result.id))
        )
        return result

    async def login(self, dto: LoginRequest, *, ip: str, user_agent: str) -> TokenPair:
        identifier = dto.identifier.strip().lower()
        rate_key = cache_key("auth", "login", identifier, ip)
        count = await self._login_attempts(rate_key)
        if count >= _LOGIN_LIMIT:
            raise AppError(AUTH_007)

        async def operation(uow: AuthUnitOfWork) -> tuple[UUID, Principal]:
            candidate = await uow.auth.find_login_candidate(identifier)
            if candidate is None:
                verify_password(dto.password, _DUMMY_PASSWORD_HASH)
                raise AppError(AUTH_001)
            if not verify_password(dto.password, candidate[1].secret_hash or ""):
                raise AppError(AUTH_001)
            user, _identity = candidate
            status = UserStatus(user.status)
            if status is not UserStatus.ACTIVE:
                raise AppError(AUTH_006)
            principal = Principal(
                id=user.id,
                username=user.username,
                roles=await uow.auth.role_names(user.id),
                capabilities=await uow.auth.capabilities(user.id),
            )
            return user.id, principal

        try:
            user_id, principal = await self._executor.read(operation)
        except AppError as exc:
            if exc.code == AUTH_001:
                count = await self._record_login_failure(rate_key)
                self._publish(
                    Event(
                        type="user.login_failed",
                        payload=UserLoginFailedPayload(
                            identifier=identifier,
                            ip=ip,
                            reason="invalid_credentials",
                        ),
                    )
                )
                if count >= _LOGIN_LIMIT:
                    raise AppError(AUTH_007) from exc
            raise

        await self._cache.delete(rate_key)
        pair = await self._issue_pair(user_id, principal, ip=ip, user_agent=user_agent)
        self._publish(
            Event(
                type="user.login_succeeded",
                payload=UserLoginSucceededPayload(user_id=user_id, ip=ip),
            )
        )
        return pair

    async def refresh(self, raw_refresh: str) -> TokenPair:
        token_hash = hash_refresh(raw_refresh)
        now = self._now()

        async def operation(uow: AuthUnitOfWork) -> TokenPair:
            stored = await uow.refresh_tokens.get_by_hash_for_update(token_hash)
            if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
                raise AppError(AUTH_003)
            user = await uow.users.get_or_none(stored.user_id)
            if user is None:
                raise AppError(AUTH_003)
            if UserStatus(user.status) is not UserStatus.ACTIVE:
                raise AppError(AUTH_006)
            stored.revoked_at = now
            stored.last_used_at = now
            principal = Principal(
                id=user.id,
                username=user.username,
                roles=await uow.auth.role_names(user.id),
                capabilities=await uow.auth.capabilities(user.id),
            )
            access = self.token_service.issue_access(principal)
            new_raw_refresh, new_refresh_hash = self.token_service.issue_refresh(user.id)
            await uow.refresh_tokens.add(
                RefreshToken(
                    id=new_uuid7(),
                    user_id=user.id,
                    token_hash=new_refresh_hash,
                    expires_at=now + timedelta(seconds=self.token_service.refresh_ttl_seconds),
                )
            )
            return TokenPair(
                access_token=access,
                refresh_token=new_raw_refresh,
                expires_in=self.token_service.access_ttl_seconds,
            )

        return await self._executor.write(operation)

    async def logout(self, raw_refresh: str) -> None:
        token_hash = hash_refresh(raw_refresh)
        now = self._now()

        async def operation(uow: AuthUnitOfWork) -> None:
            stored = await uow.refresh_tokens.get_by_hash_for_update(token_hash)
            if stored is not None and stored.revoked_at is None:
                stored.revoked_at = now

        await self._executor.write(operation)

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self._executor.write(
            lambda uow: uow.refresh_tokens.revoke_all_for_user(user_id, self._now())
        )

    async def purge_expired_tokens(self, principal: Principal | None = None) -> int:
        """Delete old revoked/expired refresh rows for the scheduled system bot."""
        del principal
        cutoff = self._now() - timedelta(days=7)

        async def operation(uow: AuthUnitOfWork) -> int:
            return await uow.refresh_tokens.purge_expired(cutoff)

        return await self._executor.write(operation)

    async def principal_from_access(self, token: str) -> Principal:
        claims: PrincipalClaims = self.token_service.verify_access(token)

        async def operation(uow: AuthUnitOfWork) -> Principal:
            user = await uow.users.get_or_none(claims.sub)
            if user is None or UserStatus(user.status) is not UserStatus.ACTIVE:
                raise AppError(AUTH_006)
            return claims.to_principal(user.username)

        return await self._executor.read(operation)

    async def me(self, principal: Principal) -> AuthMe:
        async def operation(uow: AuthUnitOfWork) -> AuthMe:
            user = await uow.users.get_or_none(principal.id)
            if user is None:
                raise AppError(AUTH_006)
            return AuthMe(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                status=UserStatus(user.status),
                roles=await uow.auth.role_names(user.id),
                capabilities=await uow.auth.capabilities(user.id),
            )

        return await self._executor.read(operation)

    async def _issue_pair(
        self,
        user_id: UUID,
        principal: Principal,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        access = self.token_service.issue_access(principal)
        raw_refresh, refresh_hash = self.token_service.issue_refresh(user_id)
        now = self._now()
        expires_at = now + timedelta(seconds=self.token_service.refresh_ttl_seconds)

        async def operation(uow: AuthUnitOfWork) -> None:
            await uow.refresh_tokens.add(
                RefreshToken(
                    id=new_uuid7(),
                    user_id=user_id,
                    token_hash=refresh_hash,
                    expires_at=expires_at,
                    user_agent=user_agent,
                    ip=ip,
                )
            )

        await self._executor.write(operation)
        return TokenPair(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=self.token_service.access_ttl_seconds,
        )

    async def _login_attempts(self, key: str) -> int:
        value = await self._cache.get(key)
        try:
            return int(value or 0)
        except ValueError:
            return 0

    async def _record_login_failure(self, key: str) -> int:
        return await self._cache.increment(key, _LOGIN_WINDOW_SECONDS)

    def _publish(self, event: Event) -> None:
        self._event_bus.publish(event)

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)
