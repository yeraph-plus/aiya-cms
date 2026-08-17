"""Epay (易支付, 彩虹版) gateway SDK client.

Python port of ``inc/adapters/Epay_Core.php`` (Yeraph Studio, GPLv3).
Covers form auto-redirect payment, mapi / refund / query API calls and
callback signature verification. Payload signing uses the legacy MD5
scheme ``md5(ksorted k=v&... joined + key)`` excluding ``sign``,
``sign_type`` and empty / ``"0"`` values — the same request shape as the
PayPal SDK flow minus its HMAC-based signing.

Deviations from the PHP original: the ``$_SERVER`` globals
(``get_client_ip`` / ``get_client_is_mobile``) become explicit
``headers`` / ``user_agent`` arguments, and TLS peer verification is
enabled by default with an explicit ``verify_ssl`` opt-out for gateways
with broken certs.
Not yet bound to ``inc.capabilities.payments.ports.PaymentProvider``.
"""

from __future__ import annotations

import html
import ipaddress
import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import md5
from typing import Any, cast

__all__ = ["EpayClient"]


def html_escape(value: str) -> str:
    """HTML-escape an attribute value (quotes included)."""

    return html.escape(value, quote=True)


class EpayClient:
    """易支付 SDK 客户端（构造时应用配置：pid / key / url / sign_type）."""

    _default_headers = (
        "Accept: */*",
        "Accept-Language: zh-CN,zh;q=0.8",
        "Connection: close",
    )

    #: 受信反代地址集合；只有对端 IP 在此集合内时才会采信转发头。
    _trusted_proxies: frozenset[str] = frozenset()

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.pid = str(config["pid"])
        self.key = str(config["key"])
        url = str(config["url"])
        # 如果 URL 没有以 "/" 结尾
        self.plat_from_url = url if url.endswith("/") else url + "/"
        # 指定签名方法
        self.sign_type = str(config.get("sign_type") or "MD5")
        # 默认校验网关证书，避免支付流量被 MITM；确需关闭时显式配置。
        self.verify_ssl = bool(config.get("verify_ssl", True))

    def _curl_http_response(
        self,
        url: str,
        post: str | None = None,
        http_header: tuple[str, ...] | None = None,
        timeout: int = 10,
    ) -> str:
        """Curl 方式请求体结构；返回响应文本."""

        headers: dict[str, str] = {}
        for line in http_header or self._default_headers:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()
        if post is not None:
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        context: ssl.SSLContext | None = None
        if not self.verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        request = urllib.request.Request(
            url,
            data=post.encode("utf-8") if post is not None else None,
            headers=headers,
            method="POST" if post is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                body = cast(bytes, response.read())
                return body.decode("utf-8", errors="replace")
        except urllib.error.URLError:
            return ""

    def _parse_result(self, response: str) -> dict[str, Any] | str:
        """解析 JSON 响应：``code == 1`` 返回结果 dict，否则返回 ``msg`` 文本."""

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            return "[Epay API] invalid response"
        if not isinstance(result, dict):
            return "[Epay API] invalid response"
        if str(result.get("code")) == "1":
            return result
        return str(result.get("msg") or "")

    def _md5_sign(self, param: dict[str, Any]) -> str:
        """计算签名：``md5(k=v&k=v&...+key)``，排除 sign/sign_type 与空值、``"0"``."""

        signstr = ""
        for key in sorted(param):
            value = param[key]
            if key not in ("sign", "sign_type") and value not in (None, False, 0, "", "0"):
                signstr += f"{key}={value}&"
        return md5((signstr[:-1] + self.key).encode("utf-8")).hexdigest()

    def _sign_param(self, param: dict[str, Any]) -> dict[str, Any]:
        """签名请求参数：追加 ``sign`` 与 ``sign_type``."""

        param["sign"] = self._md5_sign(param)
        param["sign_type"] = self.sign_type
        return param

    def get_client_ip(self, headers: Mapping[str, str]) -> str:
        """用户 IP 地址：优先取网关对端 ``REMOTE_ADDR``，仅当其属于受信代理时
        才采信 ``HTTP_X_FORWARDED_FOR`` / ``HTTP_CLIENT_IP`` 中的首个合法地址。

        反代（nginx 等）转发上游时总会改写 ``REMOTE_ADDR`` 为本机 IP，因此调用方
        必须把反代地址显式放入 ``trusted_proxies``；未知来源一律回退到对端地址，
        避免客户端伪造风险风控 IP。
        """

        def _valid(addr: str) -> str | None:
            try:
                return str(ipaddress.ip_address(addr.strip()))
            except ValueError:
                return None

        peer = _valid(headers.get("REMOTE_ADDR", ""))
        if not peer:
            return ""
        if peer not in self._trusted_proxies:
            return peer
        for name in ("HTTP_X_FORWARDED_FOR", "HTTP_CLIENT_IP"):
            raw = headers.get(name, "")
            if not raw or raw.lower() == "unknown":
                continue
            for part in raw.split(","):
                candidate = _valid(part)
                if candidate:
                    return candidate
        return peer

    @staticmethod
    def get_client_is_mobile(user_agent: str | None) -> bool:
        """用户设备类型：UA 中是否含常见移动设备标识."""

        if not user_agent:
            return False
        agent = user_agent.lower()
        return any(k in agent for k in ("iphone", "ipad", "android", "mobile", "phone"))

    def pay_auto_redirect(self, param_tmp: Mapping[str, Any], from_id: str = "bill") -> str:
        """使用 POST 发起支付（表单 HTML+JS 跳转）."""

        param = dict(param_tmp)
        param["pid"] = self.pid
        param.setdefault("type", "alipay")
        param = self._sign_param(param)

        submit_url = self.plat_from_url + "submit.php"
        html = (
            f'<form id="{html_escape(from_id)}" action="{html_escape(submit_url)}" method="post">'
        )
        for key, value in param.items():
            html += (
                f'<input type="hidden" name="{html_escape(str(key))}" '
                f'value="{html_escape(str(value))}"/>'
            )
        html += '<input type="submit" value="LOADING..."/></form>'
        html += f'<script> document.getElementById("{html_escape(from_id)}").submit(); </script>'
        return html

    def pay_mapi(
        self,
        param_tmp: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | str:
        """API 接口支付：POST ``mapi.php``，成功返回 dict，失败返回错误文本."""

        param = dict(param_tmp)
        param["pid"] = self.pid
        param.setdefault("type", "cashier")
        if "out_trade_no" not in param:
            # 拼接一个临时订单号
            param["out_trade_no"] = (
                datetime.now(UTC).strftime("%Y%m%d")
                + str(random.randint(10000, 99999))
                + str(int(time.time()))
            )
        param["clientip"] = self.get_client_ip(headers or {})
        if "device" not in param:
            param["device"] = "mobile" if self.get_client_is_mobile(user_agent) else "pc"
        param = self._sign_param(param)

        response = self._curl_http_response(
            self.plat_from_url + "mapi.php", post=urllib.parse.urlencode(param)
        )
        return self._parse_result(response)

    def pay_refund(self, trade_no: str, money: str | float) -> dict[str, Any] | str:
        """API 接口退款：POST ``?act=refund``，成功返回 dict，失败返回错误文本."""

        param = self._sign_param({"pid": self.pid, "trade_no": trade_no, "money": money})
        response = self._curl_http_response(
            self.plat_from_url + "?act=refund", post=urllib.parse.urlencode(param)
        )
        return self._parse_result(response)

    def verify_callback(self, param: Mapping[str, Any]) -> bool:
        """回调验证逻辑：重算签名并与 ``param["sign"]`` 比对."""

        if not param:
            return False
        return self._md5_sign(dict(param)) == param.get("sign")

    @staticmethod
    def get_callback_params(params: Mapping[str, str]) -> dict[str, str] | bool:
        """回调数据：非空时返回参数字典，否则返回 ``False``（PHP 版读取 ``$_GET``）."""

        if not params:
            return False
        return dict(params)

    def query_order(self, trade_no: str) -> dict[str, Any] | str:
        """API 查询单个订单：``api.php?act=order``."""

        param = self._sign_param({"act": "order", "pid": self.pid, "trade_no": trade_no})
        api_url = self.plat_from_url + "api.php?" + urllib.parse.urlencode(param)
        return self._parse_result(self._curl_http_response(api_url))

    def query_order_list(self, offset: int = 0, limit: int = 20) -> dict[str, Any] | str:
        """API 查询订单列表：``api.php?act=orders``."""

        param = self._sign_param(
            {"act": "orders", "pid": self.pid, "offset": offset, "limit": limit}
        )
        api_url = self.plat_from_url + "api.php?" + urllib.parse.urlencode(param)
        return self._parse_result(self._curl_http_response(api_url))

    def query_merchant(self) -> dict[str, Any] | str:
        """API 查询当前商户：``api.php?act=query``."""

        param = self._sign_param({"act": "query", "pid": self.pid})
        api_url = self.plat_from_url + "api.php?" + urllib.parse.urlencode(param)
        return self._parse_result(self._curl_http_response(api_url))

    def query_settlement(self) -> dict[str, Any] | str:
        """API 查询当前商户 T1 结算记录：``api.php?act=settle``."""

        param = self._sign_param({"act": "settle", "pid": self.pid})
        api_url = self.plat_from_url + "api.php?" + urllib.parse.urlencode(param)
        return self._parse_result(self._curl_http_response(api_url))
