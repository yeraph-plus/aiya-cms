"""Trusted quoting and consumption orchestration for business products."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from inc.capabilities.points import PointBehaviorSpec
from inc.kernel.errors import ErrorCategory, KernelError
from inc.kernel.security.signing import Signer

PROGRAM_KEY: Final[Literal["credit"]] = "credit"
DEBIT_BEHAVIOR_KEY: Final[Literal["business_center.consume.debit.v1"]] = (
    "business_center.consume.debit.v1"
)
ARCHIVE_PRICING_POLICY_KEY = "archive.files.fixed.v1"
ARCHIVE_PART_BYTES = 4 * 1024**3
ARCHIVE_UNIT_POINTS = 100

_KEY = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")


class EmptyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArchiveFileCost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    part_number: int = Field(ge=1)
    size_bytes: int = Field(gt=0)
    active: bool = True


class ArchiveManifestCostBasis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_ref: str = Field(min_length=1, max_length=200)
    manifest_version: str = Field(min_length=1, max_length=64)
    manifest_digest: str | None = Field(default=None, min_length=1, max_length=128)
    files: tuple[ArchiveFileCost, ...] = Field(min_length=1)


class ArchiveFulfillment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_ref: str
    manifest_version: str
    manifest_digest: str
    file_ids: tuple[str, ...]


class ArchiveConsumptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_ref: str


@dataclass(frozen=True, slots=True)
class BusinessProductSpec:
    product_key: str
    version: str
    owner: str
    pricing_policy_key: str
    fulfillment_port_key: str
    client_ids: frozenset[str]
    audience: str
    scopes: frozenset[str]
    min_points: int
    max_points: int
    quote_ttl: timedelta
    consume_cooldown: timedelta | None
    request_schema: type[BaseModel]
    cost_basis_schema: type[BaseModel]
    fulfillment_schema: type[BaseModel]
    result_schema: type[BaseModel]
    compensation_policy_version: str
    program_key: str = PROGRAM_KEY

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.product_key):
            raise ValueError(f"invalid product key {self.product_key!r}")
        if self.program_key != PROGRAM_KEY:
            raise ValueError("business products must use the credit program")
        if not self.version or not self.owner or not self.compensation_policy_version:
            raise ValueError("product version, owner and compensation policy are required")
        if not self.client_ids or not self.audience or not self.scopes:
            raise ValueError("product authentication allowlists must not be empty")
        if not 1 <= self.min_points <= self.max_points:
            raise ValueError("invalid product points range")
        if self.quote_ttl <= timedelta(0):
            raise ValueError("quote TTL must be positive")
        schemas = (
            self.request_schema,
            self.cost_basis_schema,
            self.fulfillment_schema,
            self.result_schema,
        )
        if any(
            not isinstance(schema, type) or not issubclass(schema, BaseModel) for schema in schemas
        ):
            raise ValueError("product schemas must be Pydantic models")


class BusinessProductRegistry:
    """Explicit product declarations, immutable after startup validation."""

    def __init__(
        self,
        *,
        pricing_policy_keys: frozenset[str],
        fulfillment_port_keys: frozenset[str],
        allowed_scopes: frozenset[str],
    ) -> None:
        self._pricing = pricing_policy_keys
        self._fulfillment = fulfillment_port_keys
        self._scopes = allowed_scopes
        self._products: dict[str, BusinessProductSpec] = {}
        self._frozen = False

    def register(self, spec: BusinessProductSpec) -> None:
        if self._frozen:
            raise _error(
                "business_center.registry_frozen", ErrorCategory.INTERNAL, "registry frozen"
            )
        if spec.product_key in self._products:
            raise _error(
                "business_center.duplicate_product",
                ErrorCategory.INTERNAL,
                f"duplicate product {spec.product_key}",
            )
        if spec.pricing_policy_key not in self._pricing:
            raise _error(
                "business_center.unknown_pricing_policy",
                ErrorCategory.INTERNAL,
                f"unknown pricing policy {spec.pricing_policy_key}",
            )
        if spec.fulfillment_port_key not in self._fulfillment:
            raise _error(
                "business_center.unknown_fulfillment_port",
                ErrorCategory.INTERNAL,
                f"unknown fulfillment port {spec.fulfillment_port_key}",
            )
        if not spec.scopes <= self._scopes:
            raise _error(
                "business_center.unknown_scope",
                ErrorCategory.INTERNAL,
                "product declares an unregistered scope",
            )
        self._products[spec.product_key] = spec

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def require(self, product_key: str) -> BusinessProductSpec:
        product = self._products.get(product_key)
        if product is None:
            raise _error(
                "business_center.unknown_product",
                ErrorCategory.VALIDATION,
                "unknown business product",
            )
        return product

    def specs(self) -> tuple[BusinessProductSpec, ...]:
        return tuple(self._products[key] for key in sorted(self._products))


class PriceExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_name: str
    unit_count: int = Field(gt=0)
    unit_points: int = Field(gt=0)


class PricingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: int = Field(gt=0)
    target_digest: str
    explanation: PriceExplanation
    fulfillment: ArchiveFulfillment


def price_archive_files_fixed_v1(cost_basis: ArchiveManifestCostBasis) -> PricingResult:
    """Price a complete, ordered 4 GiB archive manifest without external IO."""

    files = tuple(sorted(cost_basis.files, key=lambda item: item.part_number))
    if any(not item.active for item in files):
        raise _error(
            "business_center.quote_stale", ErrorCategory.CONFLICT, "manifest has inactive files"
        )
    if len({item.file_id for item in files}) != len(files) or tuple(
        item.part_number for item in files
    ) != tuple(range(1, len(files) + 1)):
        raise _error(
            "business_center.invalid_cost_basis",
            ErrorCategory.VALIDATION,
            "manifest files must have unique IDs and contiguous part numbers",
        )
    if any(item.size_bytes != ARCHIVE_PART_BYTES for item in files[:-1]) or not (
        0 < files[-1].size_bytes <= ARCHIVE_PART_BYTES
    ):
        raise _error(
            "business_center.invalid_cost_basis",
            ErrorCategory.VALIDATION,
            "manifest does not follow 4 GiB part sizing",
        )
    snapshot = {
        "manifest_version": cost_basis.manifest_version,
        "files": [
            {
                "file_id": item.file_id,
                "version": item.version,
                "part_number": item.part_number,
                "size_bytes": item.size_bytes,
            }
            for item in files
        ],
        "file_count": len(files),
    }
    digest = cost_basis.manifest_digest or hashlib.sha256(_canonical(snapshot)).hexdigest()
    return PricingResult(
        amount=len(files) * ARCHIVE_UNIT_POINTS,
        target_digest=digest,
        explanation=PriceExplanation(
            unit_name="active_file", unit_count=len(files), unit_points=ARCHIVE_UNIT_POINTS
        ),
        fulfillment=ArchiveFulfillment(
            target_ref=cost_basis.target_ref,
            manifest_version=cost_basis.manifest_version,
            manifest_digest=digest,
            file_ids=tuple(item.file_id for item in files),
        ),
    )


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_key: str
    target_ref: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class BusinessPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=200)
    client_id: str = Field(min_length=1, max_length=200)
    audience: str = Field(min_length=1, max_length=200)
    scopes: frozenset[str] = Field(min_length=1)


class QuoteClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_id: str
    product_key: str
    product_version: str
    pricing_policy_key: str
    compensation_policy_version: str
    program_key: Literal["credit"] = PROGRAM_KEY
    amount: int
    target_ref: str
    target_digest: str
    parameters: dict[str, Any]
    subject: str
    client_id: str
    audience: str
    issued_at: datetime
    expires_at: datetime
    fulfillment: ArchiveFulfillment


class BusinessQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_id: str
    product_key: str
    product_version: str
    pricing_policy_key: str
    program_key: Literal["credit"] = PROGRAM_KEY
    amount: int
    explanation: PriceExplanation
    target_digest: str
    expires_at: datetime
    token: str


class QuoteTokenCodec:
    def __init__(self, signer: Signer) -> None:
        self._signer = signer

    def encode(self, claims: QuoteClaims) -> str:
        payload = _canonical(claims.model_dump(mode="json"))
        return f"{_b64(payload)}.{_b64(self._signer.sign(payload))}"

    def decode(self, token: str) -> QuoteClaims:
        try:
            payload_part, signature_part = token.split(".", 1)
            payload = _unb64(payload_part)
            signature = _unb64(signature_part)
            if _b64(payload) != payload_part or _b64(signature) != signature_part:
                raise ValueError("non-canonical token encoding")
            if not self._signer.verify(payload, signature):
                raise ValueError("signature mismatch")
            return QuoteClaims.model_validate_json(payload)
        except (ValueError, TypeError) as exc:
            raise _error(
                "business_center.invalid_quote",
                ErrorCategory.VALIDATION,
                "quote token is invalid",
            ) from exc


class CostBasisPort(Protocol):
    async def resolve(
        self, *, product: BusinessProductSpec, target_ref: str, parameters: BaseModel
    ) -> BaseModel: ...


class PointsDebitPort(Protocol):
    async def debit(self, request: DebitRequest) -> str: ...


class FulfillmentPort(Protocol):
    async def fulfill(self, request: FulfillmentRequest) -> str: ...


class Clock(Protocol):
    def utc_now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class DebitRequest:
    behavior_key: Literal["business_center.consume.debit.v1"]
    program_key: Literal["credit"]
    subject: str
    amount: int
    source_ref: str
    idempotency_key: str
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class FulfillmentRequest:
    port_key: str
    subject: str
    client_id: str
    product_key: str
    quote_id: str
    points_entry_ref: str
    payload: ArchiveFulfillment
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ConsumptionRecord:
    consumption_id: str
    idempotency_key: str
    claims: QuoteClaims
    status: Literal["pending_debit", "fulfillment_pending", "fulfilled"]
    points_entry_ref: str | None = None
    fulfillment_ref: str | None = None


class ConsumptionStatePort(Protocol):
    async def get_or_create(self, record: ConsumptionRecord) -> ConsumptionRecord: ...

    async def save(self, record: ConsumptionRecord) -> None: ...


class QuoteBusinessProduct:
    def __init__(
        self,
        *,
        products: BusinessProductRegistry,
        cost_basis: CostBasisPort,
        token_codec: QuoteTokenCodec,
        clock: Clock,
    ) -> None:
        self._products = products
        self._cost_basis = cost_basis
        self._tokens = token_codec
        self._clock = clock

    async def __call__(
        self, request: QuoteRequest, *, principal: BusinessPrincipal
    ) -> BusinessQuote:
        product = self._products.require(request.product_key)
        _authorize(product, principal, action_scope="business.quote")
        parameters = product.request_schema.model_validate(request.parameters)
        basis = product.cost_basis_schema.model_validate(
            await self._cost_basis.resolve(
                product=product, target_ref=request.target_ref, parameters=parameters
            )
        )
        if getattr(basis, "target_ref", request.target_ref) != request.target_ref:
            raise _error(
                "business_center.invalid_cost_basis",
                ErrorCategory.INTERNAL,
                "cost basis does not match requested target",
            )
        pricing = _price(product.pricing_policy_key, basis)
        if not product.min_points <= pricing.amount <= product.max_points:
            raise _error(
                "business_center.invalid_price",
                ErrorCategory.INTERNAL,
                "trusted price is outside product limits",
            )
        now = _utc(self._clock.utc_now())
        claims = QuoteClaims(
            quote_id=str(uuid.uuid4()),
            product_key=product.product_key,
            product_version=product.version,
            pricing_policy_key=product.pricing_policy_key,
            compensation_policy_version=product.compensation_policy_version,
            amount=pricing.amount,
            target_ref=request.target_ref,
            target_digest=pricing.target_digest,
            parameters=parameters.model_dump(mode="json"),
            subject=principal.subject,
            client_id=principal.client_id,
            audience=principal.audience,
            issued_at=now,
            expires_at=now + product.quote_ttl,
            fulfillment=pricing.fulfillment,
        )
        return BusinessQuote(
            quote_id=claims.quote_id,
            product_key=claims.product_key,
            product_version=claims.product_version,
            pricing_policy_key=claims.pricing_policy_key,
            amount=claims.amount,
            explanation=pricing.explanation,
            target_digest=claims.target_digest,
            expires_at=claims.expires_at,
            token=self._tokens.encode(claims),
        )


class ConsumeBusinessProduct:
    def __init__(
        self,
        *,
        products: BusinessProductRegistry,
        cost_basis: CostBasisPort,
        token_codec: QuoteTokenCodec,
        points: PointsDebitPort,
        fulfillments: Mapping[str, FulfillmentPort],
        state: ConsumptionStatePort,
        clock: Clock,
    ) -> None:
        self._products = products
        self._cost_basis = cost_basis
        self._tokens = token_codec
        self._points = points
        self._fulfillments = fulfillments
        self._state = state
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}

    async def __call__(
        self,
        *,
        quote_token: str,
        idempotency_key: str,
        principal: BusinessPrincipal,
    ) -> ConsumptionRecord:
        if not idempotency_key or len(idempotency_key) > 200:
            raise _error(
                "business_center.invalid_idempotency_key",
                ErrorCategory.VALIDATION,
                "idempotency key is required",
            )
        claims = self._tokens.decode(quote_token)
        product = self._products.require(claims.product_key)
        _authorize(product, principal, action_scope="business.consume")
        if (
            claims.subject != principal.subject
            or claims.client_id != principal.client_id
            or claims.audience != principal.audience
        ):
            raise _error(
                "business_center.invalid_quote",
                ErrorCategory.FORBIDDEN,
                "quote is bound to another subject or client",
            )
        consumption_key = _digest(f"{principal.subject}\0{claims.quote_id}\0{idempotency_key}")
        async with self._locks.setdefault(consumption_key, asyncio.Lock()):
            candidate = ConsumptionRecord(
                consumption_id=consumption_key,
                idempotency_key=idempotency_key,
                claims=claims,
                status="pending_debit",
            )
            record = await self._state.get_or_create(candidate)
            if (
                record.claims.quote_id != claims.quote_id
                or record.claims.subject != principal.subject
            ):
                raise _error(
                    "business_center.idempotency_mismatch",
                    ErrorCategory.CONFLICT,
                    "idempotency key is bound to another consumption",
                )
            if record.status == "fulfilled":
                return record
            if record.points_entry_ref is None:
                await self._validate_fresh_quote(product, claims)
                try:
                    entry_ref = await self._points.debit(
                        DebitRequest(
                            behavior_key=DEBIT_BEHAVIOR_KEY,
                            program_key=PROGRAM_KEY,
                            subject=principal.subject,
                            amount=claims.amount,
                            source_ref=claims.quote_id,
                            idempotency_key=f"{consumption_key}:debit",
                            metadata={
                                "product_key": product.product_key,
                                "quote_id": claims.quote_id,
                                "client_id": principal.client_id,
                            },
                        )
                    )
                except KernelError as exc:
                    if exc.code == "points.insufficient_balance":
                        raise _error(
                            "business_center.insufficient_balance",
                            ErrorCategory.CONFLICT,
                            "insufficient credit balance",
                        ) from exc
                    raise
                record = replace(record, status="fulfillment_pending", points_entry_ref=entry_ref)
                await self._state.save(record)
            assert record.points_entry_ref is not None
            fulfillment = self._fulfillments.get(product.fulfillment_port_key)
            if fulfillment is None:
                raise _error(
                    "business_center.fulfillment_unavailable",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    "fulfillment port is unavailable",
                )
            try:
                fulfillment_ref = await fulfillment.fulfill(
                    FulfillmentRequest(
                        port_key=product.fulfillment_port_key,
                        subject=principal.subject,
                        client_id=principal.client_id,
                        product_key=product.product_key,
                        quote_id=claims.quote_id,
                        points_entry_ref=record.points_entry_ref,
                        payload=claims.fulfillment,
                        idempotency_key=f"{consumption_key}:fulfill",
                    )
                )
            except FulfillmentTemporarilyUnavailable:
                return record
            except KernelError as exc:
                if exc.category == ErrorCategory.DEPENDENCY_UNAVAILABLE:
                    return record
                raise
            record = replace(record, status="fulfilled", fulfillment_ref=fulfillment_ref)
            await self._state.save(record)
            return record

    async def _validate_fresh_quote(
        self, product: BusinessProductSpec, claims: QuoteClaims
    ) -> None:
        if (
            _utc(self._clock.utc_now()) >= _utc(claims.expires_at)
            or claims.product_version != product.version
            or claims.pricing_policy_key != product.pricing_policy_key
            or claims.compensation_policy_version != product.compensation_policy_version
            or claims.program_key != PROGRAM_KEY
        ):
            raise _stale()
        basis = product.cost_basis_schema.model_validate(
            await self._cost_basis.resolve(
                product=product,
                target_ref=claims.target_ref,
                parameters=product.request_schema.model_validate(claims.parameters),
            )
        )
        if getattr(basis, "target_ref", claims.target_ref) != claims.target_ref:
            raise _stale()
        current = _price(product.pricing_policy_key, basis)
        if current.target_digest != claims.target_digest or current.amount != claims.amount:
            raise _stale()


class FulfillmentTemporarilyUnavailable(Exception):
    """A retryable provider failure after a durable debit."""


def archive_product_spec(
    *, client_ids: frozenset[str], audience: str, quote_ttl: timedelta = timedelta(minutes=5)
) -> BusinessProductSpec:
    return BusinessProductSpec(
        product_key="archive.download.manifest",
        version="1",
        owner="archive",
        pricing_policy_key=ARCHIVE_PRICING_POLICY_KEY,
        fulfillment_port_key="archive.issue_download_grant.v1",
        client_ids=client_ids,
        audience=audience,
        scopes=frozenset({"business.quote", "business.consume", "archive.download"}),
        min_points=ARCHIVE_UNIT_POINTS,
        max_points=1_000_000,
        quote_ttl=quote_ttl,
        consume_cooldown=None,
        request_schema=EmptyParameters,
        cost_basis_schema=ArchiveManifestCostBasis,
        fulfillment_schema=ArchiveFulfillment,
        result_schema=ArchiveConsumptionResult,
        compensation_policy_version="1",
    )


behavior_specs = (
    PointBehaviorSpec(
        key=DEBIT_BEHAVIOR_KEY,
        version="1",
        program_key=PROGRAM_KEY,
        direction="debit",
        min_amount=1,
        max_amount=1_000_000,
        allowed_source_types=("business_center",),
    ),
)


def _price(policy_key: str, basis: BaseModel) -> PricingResult:
    if policy_key != ARCHIVE_PRICING_POLICY_KEY:
        raise _error(
            "business_center.unknown_pricing_policy",
            ErrorCategory.INTERNAL,
            "pricing policy is unavailable",
        )
    return price_archive_files_fixed_v1(ArchiveManifestCostBasis.model_validate(basis))


def _authorize(
    product: BusinessProductSpec,
    principal: BusinessPrincipal,
    *,
    action_scope: Literal["business.quote", "business.consume"],
) -> None:
    if principal.client_id not in product.client_ids:
        raise _error(
            "business_center.client_forbidden",
            ErrorCategory.FORBIDDEN,
            "client is not allowed to use this product",
        )
    product_scopes = {
        scope for scope in product.scopes if scope not in {"business.quote", "business.consume"}
    }
    if principal.audience != product.audience or not ({action_scope} | product_scopes) <= set(
        principal.scopes
    ):
        raise _error(
            "business_center.authorization_invalid",
            ErrorCategory.FORBIDDEN,
            "token audience or scopes do not authorize this operation",
        )


def _stale() -> KernelError:
    return _error(
        "business_center.quote_stale", ErrorCategory.CONFLICT, "quote is no longer current"
    )


def _error(code: str, category: ErrorCategory, message: str) -> KernelError:
    return KernelError(code=code, category=category, message=message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ARCHIVE_PART_BYTES",
    "ARCHIVE_PRICING_POLICY_KEY",
    "ARCHIVE_UNIT_POINTS",
    "ArchiveFileCost",
    "ArchiveManifestCostBasis",
    "BusinessProductRegistry",
    "BusinessProductSpec",
    "BusinessPrincipal",
    "BusinessQuote",
    "ConsumeBusinessProduct",
    "ConsumptionRecord",
    "DebitRequest",
    "FulfillmentRequest",
    "FulfillmentTemporarilyUnavailable",
    "QuoteBusinessProduct",
    "QuoteRequest",
    "QuoteTokenCodec",
    "archive_product_spec",
    "behavior_specs",
    "price_archive_files_fixed_v1",
]
