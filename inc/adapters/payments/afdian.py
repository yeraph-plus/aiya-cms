"""Afdian (爱发电) platform API SDK client.

Python port of ``inc/adapters/Afdian_API.php`` (Yeraph Studio, GPLv3).
Signed API queries (ping / order / sponsor) against
``https://ifdian.net/api/open/...``, mirroring the PHP class semantics:
a failed request returns an ``AfdianHttpError`` carrying the response
text instead of raising, and query methods return the parsed JSON dict
on ``ec == 200`` or the error message string otherwise.

Method names are snake_case and the PHP ``serach_*`` typo is fixed to
``search_*``; the public surface is otherwise identical. Passive webhook
verification (``handle_webhook``) follows the official RSA-SHA256 scheme
with the public key in ``AFDIAN_WEBHOOK_PUBLIC_KEY``. Not yet bound to
``inc.capabilities.payments.ports.PaymentProvider``.

字段表（依据爱发电开发者文档 https://ifdian.net/doc）::

    通用请求（每次 POST 的顶层字段）
    | 字段    | 类型   | 说明                          |
    |---------|--------|-------------------------------|
    | user_id | string | 开发者后台的 user_id          |
    | params  | string | 具体接口参数的 JSON 字符串     |
    | ts      | int    | 发出请求时的秒级时间戳         |
    | sign    | string | 签名，规则见下                |

    签名规则: sign = md5(token + "params" + params + "ts" + ts +
    "user_id" + user_id)，token 不传给服务器，仅参与签名计算。

    错误码（响应 ec 字段）
    | ec     | 说明                              |
    |--------|-----------------------------------|
    | 400001 | params incomplete                |
    | 400002 | time was expired，允许 3600s 延迟 |
    | 400003 | params was not valid json string |
    | 400004 | no valid token found             |
    | 400005 | sign validation failed           |

    Webhook 请求（平台 POST 到配置 URL，data.type 目前仅为 "order"）
    | 字段       | 类型   | 说明                                                    |
    |------------|--------|---------------------------------------------------------|
    | ec         | int    | 固定 200                                                |
    | em         | string | 固定 "ok"                                               |
    | data.type  | string | 事件类型，目前仅为 "order"                              |
    | data.order | object | 订单对象，字段见下方订单字段表                          |
    | data.sign  | string | RSA-SHA256 验签 out_trade_no+user_id+plan_id+total_amount 的 base64 |

    Webhook 响应：需返回 {"ec": 200, "em": ""}，不返回 ec 200 则平台
    视为回调失败；平台可能重复推送，建议按 out_trade_no 做幂等处理。

    订单字段（webhook 的 data.order 与 query-order 返回 list 中元素一致）
    | 字段             | 类型   | 说明                                 |
    |------------------|--------|--------------------------------------|
    | out_trade_no     | string | 订单号                               |
    | custom_order_id  | string | 自定义信息，可经前端 URL 传参         |
    | user_id          | string | 下单用户 ID                          |
    | user_private_id  | string | 用户唯一 ID，类似微信 unionid        |
    | plan_id          | string | 方案 ID，自选则为空                  |
    | month            | int    | 赞助月份                             |
    | total_amount     | string | 真实付款金额，有兑换码则为 0.00      |
    | show_amount      | string | 显示金额，有折扣则为折扣前金额        |
    | status           | int    | 2 为交易成功，目前仅推送此类型        |
    | remark           | string | 订单留言                             |
    | redeem_id        | string | 兑换码 ID                            |
    | product_type     | int    | 0 常规方案，1 售卖方案               |
    | discount         | string | 折扣                                 |
    | sku_detail       | array  | 售卖型号明细，含 sku_id/count/name/album_id/pic |
    | address_person   | string | 收件人                               |
    | address_phone    | string | 收件人电话                           |
    | address_address  | string | 收件人地址                           |

    赞助者字段（query-sponsor 返回 list 中元素）
    | 字段            | 类型   | 说明                                  |
    |-----------------|--------|---------------------------------------|
    | sponsor_plans   | array  | 赞助方案列表                          |
    | current_plan    | object | 当前方案，仅含 name:"" 表示无方案     |
    | all_sum_amount  | string | 累计赞助金额（折扣前）                |
    | create_time     | int    | 首次赞助时间，秒级时间戳              |
    | last_pay_time   | int    | 最近赞助时间，秒级时间戳              |
    | user.user_id    | string | 用户唯一 ID                           |
    | user.name       | string | 昵称，非唯一可重复                    |
    | user.avatar     | string | 头像                                  |
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import md5
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

__all__ = ["AfdianClient", "AfdianHttpError"]

#: 爱发电官方 Webhook 验签公钥（开发者文档公开固定值）。
AFDIAN_WEBHOOK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwwdaCg1Bt+UKZKs0R54y
lYnuANma49IpgoOwNmk3a0rhg/PQuhUJ0EOZSowIC44l0K3+fqGns3Ygi4AfmEfS
4EKbdk1ahSxu7Zkp2rHMt+R9GarQFQkwSS/5x1dYiHNVMiR8oIXDgjmvxuNes2Cr
8fw9dEF0xNBKdkKgG2qAawcN1nZrdyaKWtPVT9m2Hl0ddOO9thZmVLFOb9NVzgYf
jEgI+KWX6aY19Ka/ghv/L4t1IXmz9pctablN5S0CRWpJW3Cn0k6zSXgjVdKm4uN7
jRlgSRaf/Ind46vMCm3N2sgwxu/g3bnooW+db0iLo13zzuvyn727Q3UDQ0MmZcEW
MQIDAQAB
-----END PUBLIC KEY-----"""


@dataclass
class AfdianHttpError:
    """HTTP-level failure; mirrors PHP ``AYA_HTTP_Response`` usage."""

    status: int
    data: str


class AfdianClient:
    """Afdian API client (初始化: ``Afdian_API(user_id, token)``)."""

    api_root_url = "https://ifdian.net/api/open/%s"

    def __init__(self, user_id: str, token: str) -> None:
        self.user_id = user_id
        self.token = token

    def _get_signature(self, params: str, ts: int) -> str:
        """计算 API 请求签名: md5(token + "params" + params + "ts" + ts + "user_id" + user_id)."""

        raw = f"{self.token}params{params}ts{ts}user_id{self.user_id}"
        return md5(raw.encode("utf-8")).hexdigest()

    def query_server(
        self, api: str, params: dict[str, Any]
    ) -> dict[str, Any] | AfdianHttpError | None:
        """查询入口；返回解析后的 JSON dict 或 ``AfdianHttpError``."""

        if not api:
            return None

        params_json = json.dumps(params, ensure_ascii=True, separators=(",", ":"))
        ts = int(time.time())
        query_data = json.dumps(
            {
                "user_id": self.user_id,
                "params": params_json,
                "ts": ts,
                "sign": self._get_signature(params_json, ts),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )

        request = urllib.request.Request(
            self.api_root_url % api,
            data=query_data.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            return AfdianHttpError(
                status=400,
                data=f"[Afdian API] Client request failed: {exc.reason} (0)",
            )

        if status != 200:
            return AfdianHttpError(
                status=400,
                data=f"[Afdian API] Client request failed: {body} ({status})",
            )

        try:
            response_json = json.loads(body)
        except json.JSONDecodeError:
            return AfdianHttpError(
                status=400, data=f"[Afdian API] Response data: {body} ({status})"
            )
        if not isinstance(response_json, dict):
            return AfdianHttpError(
                status=400, data=f"[Afdian API] Response data: {body} ({status})"
            )
        return response_json

    def _query(self, api: str, params: dict[str, Any]) -> dict[str, Any] | str:
        """查询入口；成功且 ``ec == 200`` 返回完整 dict，否则返回错误文本."""

        result = self.query_server(api, params)
        if isinstance(result, AfdianHttpError):
            return result.data
        if result is None:
            return ""
        if result.get("ec") == 200:
            return result
        return str(result.get("em") or "")

    def ping_server(self) -> bool | str:
        """Ping 方法；联通时返回 ``True``，否则返回错误文本.

        对应测试接口 https://ifdian.net/api/open/ping，签名校验通过时
        响应 ``ec == 200``、``em == "pong"``。
        """

        result = self.query_server("ping", {"ping": "hello world"})
        if isinstance(result, AfdianHttpError):
            return result.data
        return result is not None and result.get("ec") == 200

    def query_order(self, order: str = "") -> dict[str, Any] | str:
        """查询指定订单号，成功返回完整 dict，失败返回错误文本.

        params 请求字段（query-order）::

            | 字段         | 类型   | 必填 | 说明                             |
            |--------------|--------|------|----------------------------------|
            | page         | int    | 否   | 页数，从 1 累加，按创建时间倒序    |
            | per_page     | int    | 否   | 每页条数，默认 50，支持 1-100     |
            | out_trade_no | string | 否   | 指定订单号，多个用英文逗号分隔     |

        返回 data 字段::

            | 字段        | 类型  | 说明                                        |
            |-------------|-------|---------------------------------------------|
            | list        | array | 订单列表，元素字段见模块 docstring 订单字段表 |
            | total_count | int   | 订单总数                                    |
            | total_page  | int   | 总页数，curr_page < total_page 可继续请求    |
        """

        return self._query("query-order", {"out_trade_no": order})

    def query_sponsor(self, sponsor: str = "") -> dict[str, Any] | str:
        """查询指定用户赞助情况，成功返回完整 dict，失败返回错误文本.

        params 请求字段（query-sponsor）::

            | 字段    | 类型   | 必填 | 说明                             |
            |---------|--------|------|----------------------------------|
            | page    | int    | 否   | 页数，从 1 累加，按关系建立倒序    |
            | per_page| int    | 否   | 每页条数，默认 20，支持 1-100     |
            | user_id | string | 否   | 指定用户，多个用英文逗号分隔       |

        返回 data 字段::

            | 字段        | 类型  | 说明                                        |
            |-------------|-------|---------------------------------------------|
            | list        | array | 赞助者列表，元素字段见模块 docstring 赞助者字段表 |
            | total_count | int   | 赞助者总数                                  |
            | total_page  | int   | 总页数，curr_page < total_page 可继续请求    |
        """

        return self._query("query-sponsor", {"user_id": sponsor})

    def get_orders(self, page: int = 1, per_page: int = 50) -> dict[str, Any] | str:
        """返回订单列表（分页），成功返回完整 dict，失败返回错误文本.

        请求/返回字段同 ``query_order``。
        """

        return self._query("query-order", {"page": page, "per_page": per_page})

    def get_sponsors(self, page: int = 1, per_page: int = 20) -> dict[str, Any] | str:
        """返回赞助者列表（分页），成功返回完整 dict，失败返回错误文本.

        请求/返回字段同 ``query_sponsor``。
        """

        return self._query("query-sponsor", {"page": page, "per_page": per_page})

    def get_all_orders(self) -> dict[str, Any] | str:
        """获取所有订单（循环分页合并，不返回 total_page）."""

        orders: dict[str, Any] = {"data": {"list": []}}

        result = self.get_orders(1)
        if not isinstance(result, dict):
            return result

        data = result.get("data")
        if isinstance(data, dict):
            lst = data.get("list")
            total_page = data.get("total_page")
            if isinstance(lst, list) and isinstance(total_page, int):
                orders["data"]["list"].extend(lst)
                for page in range(2, total_page + 1):
                    result = self.get_orders(page)
                    if isinstance(result, dict):
                        page_data = result.get("data")
                        if isinstance(page_data, dict) and isinstance(page_data.get("list"), list):
                            orders["data"]["list"].extend(page_data["list"])
        return orders

    def get_all_sponsors(self) -> dict[str, Any] | str:
        """获取所有赞助者名单（循环分页合并）."""

        sponsors: dict[str, Any] = {"data": {"list": []}}

        result = self.get_sponsors(1)
        if not isinstance(result, dict):
            return result

        data = result.get("data")
        if isinstance(data, dict):
            lst = data.get("list")
            total_page = data.get("total_page")
            if isinstance(lst, list) and isinstance(total_page, int):
                sponsors["data"]["list"].extend(lst)
                for page in range(2, total_page + 1):
                    result = self.get_sponsors(page)
                    if isinstance(result, dict):
                        page_data = result.get("data")
                        if isinstance(page_data, dict) and isinstance(page_data.get("list"), list):
                            sponsors["data"]["list"].extend(page_data["list"])
        return sponsors

    def verify_webhook_sign(self, sign_str: str, signature: str) -> bool:
        """RSA-SHA256 验签（对应官方文档 ``verifySign``）.

        验签串 ``sign_str`` 为 order 中 out_trade_no、user_id、plan_id、
        total_amount 依次拼接；``signature`` 为 payload ``data.sign`` 的
        base64 值。
        """

        if not signature:
            return False
        try:
            public_key = cast(
                rsa.RSAPublicKey,
                serialization.load_pem_public_key(AFDIAN_WEBHOOK_PUBLIC_KEY.encode("utf-8")),
            )
            public_key.verify(
                base64.b64decode(signature),
                sign_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature, ValueError:
            return False
        return True

    def handle_webhook(self, body: bytes) -> dict[str, Any] | str:
        """被动 webhook 处理：解析事件并验签订单回调.

        按文档，签名在 payload 的 ``data.sign``，验签串为 order 中
        ``out_trade_no + user_id + plan_id + total_amount`` 依次拼接。
        ``data.type`` 目前仅为 ``"order"``。

        成功返回 ``data`` 内容；签名不匹配或请求体不合法返回错误文本，
        此时调用方应回非 200 响应，让爱发电按策略重试。平台可能重复推送，
        建议调用方以 ``out_trade_no`` 做幂等处理。
        """

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError, UnicodeDecodeError:
            return "[Afdian API] Webhook invalid body"
        if not isinstance(payload, dict):
            return "[Afdian API] Webhook invalid body"
        data = payload.get("data")
        if not isinstance(data, dict):
            return "[Afdian API] Webhook invalid body"
        if data.get("type") != "order":
            return "[Afdian API] Webhook unknown type"
        order = data.get("order")
        sign = data.get("sign")
        if not isinstance(order, dict) or not isinstance(sign, str):
            return "[Afdian API] Webhook invalid body"
        sign_str = "".join(
            str(order.get(key, ""))
            for key in ("out_trade_no", "user_id", "plan_id", "total_amount")
        )
        if not self.verify_webhook_sign(sign_str, sign):
            return "[Afdian API] Webhook signature mismatch"
        return data

    def webhook_ok_response(self) -> dict[str, Any]:
        """爱发电要求的本机响应回执: ``{"ec": 200, "em": ""}``.

        不返回 ``ec == 200`` 则平台认为回调失败。
        """

        return {"ec": 200, "em": ""}

    def search_order(self, result: dict[str, Any], order_id: str) -> dict[str, Any] | None:
        """从取得列表中搜索订单；未找到返回 ``None``."""

        data = result.get("data")
        if isinstance(data, dict):
            for order in data.get("list", []):
                if isinstance(order, dict) and str(order.get("out_trade_no")) == str(order_id):
                    return order
        return None

    def search_user(self, result: dict[str, Any], user_id: str) -> dict[str, Any] | None:
        """从取得列表中搜索用户；未找到返回 ``None``."""

        data = result.get("data")
        if isinstance(data, dict):
            for sponsor in data.get("list", []):
                if isinstance(sponsor, dict):
                    user = sponsor.get("user")
                    if isinstance(user, dict) and str(user.get("user_id")) == str(user_id):
                        return sponsor
        return None

    def search_user_name(self, result: dict[str, Any], user_name: str) -> dict[str, Any] | None:
        """从取得列表中搜索用户名；未找到返回 ``None``."""

        data = result.get("data")
        if isinstance(data, dict):
            for sponsor in data.get("list", []):
                if isinstance(sponsor, dict):
                    user = sponsor.get("user")
                    if isinstance(user, dict) and str(user.get("name")) == str(user_name):
                        return sponsor
        return None

    def list_plan_order(self, result: dict[str, Any], plan_id: str | int) -> list[dict[str, Any]]:
        """从取得列表中查询指定方案的订单列表."""

        orders: list[dict[str, Any]] = []
        data = result.get("data")
        if isinstance(data, dict):
            for order in data.get("list", []):
                if isinstance(order, dict) and str(order.get("plan_id")) == str(plan_id):
                    orders.append(order)
        return orders

    def list_user_order(self, result: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
        """从取得列表中查询指定用户的订单列表."""

        orders: list[dict[str, Any]] = []
        data = result.get("data")
        if isinstance(data, dict):
            for order in data.get("list", []):
                if isinstance(order, dict) and str(order.get("user_id")) == str(user_id):
                    orders.append(order)
        return orders
