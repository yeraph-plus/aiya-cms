"""Epay adapter unit tests.

Contract source: context/spec/adapters.md §4.

Covers payment-form HTML escaping (XSS) and TLS verification defaults.
"""

from __future__ import annotations

from inc.adapters.payments.epay import EpayClient


def test_pay_auto_redirect_escapes_attributes() -> None:
    client = EpayClient({"pid": "1001", "key": "k", "url": "https://pay.example.com/"})
    html = client.pay_auto_redirect(
        {"name": '"><script>alert(1)</script>', "notify_url": 'x" autofocus onfocus="alert(2)'},
        from_id='bill" onmouseover="alert(3)',
    )
    assert "<script>alert(1)</script>" not in html
    assert 'onfocus="alert(2)"' not in html
    assert 'onmouseover="alert(3)"' not in html
    assert "&quot;&gt;&lt;script&gt;" in html or "&#34;&gt;&lt;script&gt;" in html
    assert 'value="&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in html


def test_verify_ssl_defaults_to_true() -> None:
    client = EpayClient({"pid": "1001", "key": "k", "url": "https://pay.example.com/"})
    assert client.verify_ssl is True


def test_verify_ssl_explicit_optout() -> None:
    client = EpayClient(
        {"pid": "1001", "key": "k", "url": "https://pay.example.com/", "verify_ssl": False}
    )
    assert client.verify_ssl is False


def test_get_client_ip_uses_peer_when_untrusted() -> None:
    """Forwarded headers must be ignored unless REMOTE_ADDR is a trusted proxy,
    so an attacker cannot spoof the risk-control IP."""
    client = EpayClient({"pid": "1001", "key": "k", "url": "https://pay.example.com/"})
    assert (
        client.get_client_ip({"REMOTE_ADDR": "1.2.3.4", "HTTP_X_FORWARDED_FOR": "9.9.9.9"})
        == "1.2.3.4"
    )
    assert (
        client.get_client_ip({"REMOTE_ADDR": "1.2.3.4", "HTTP_CLIENT_IP": "9.9.9.9"}) == "1.2.3.4"
    )


def test_get_client_ip_validates_format() -> None:
    client = EpayClient({"pid": "1001", "key": "k", "url": "https://pay.example.com/"})
    assert client.get_client_ip({"REMOTE_ADDR": "999.999.999.999"}) == ""
    assert client.get_client_ip({}) == ""
    assert client.get_client_ip({"HTTP_X_FORWARDED_FOR": "6.6.6.6"}) == ""
    assert client.get_client_ip({"REMOTE_ADDR": "::1"}) == "::1"


def test_get_client_ip_trusts_forwarded_from_known_proxy() -> None:
    client = EpayClient({"pid": "1001", "key": "k", "url": "https://pay.example.com/"})
    client._trusted_proxies = frozenset({"1.2.3.4"})
    assert (
        client.get_client_ip({"REMOTE_ADDR": "1.2.3.4", "HTTP_X_FORWARDED_FOR": "9.9.9.9, 8.8.8.8"})
        == "9.9.9.9"
    )
    assert (
        client.get_client_ip({"REMOTE_ADDR": "1.2.3.4", "HTTP_X_FORWARDED_FOR": "unknown, 5.5.5.5"})
        == "5.5.5.5"
    )
