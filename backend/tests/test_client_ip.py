"""Client IP resolution: X-Forwarded-For is honoured only from TRUSTED_PROXIES."""
from __future__ import annotations

import pytest
from app import security
from app.config import Settings
from app.security import client_ip, parse_trusted_proxies, resolve_client_ip
from starlette.requests import Request

PRIVATE = parse_trusted_proxies("127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1, fc00::/7")
ANY = parse_trusted_proxies("*")
NONE = parse_trusted_proxies("")


def test_direct_client_without_header():
    assert resolve_client_ip("203.0.113.7", "", PRIVATE) == "203.0.113.7"


def test_untrusted_peer_cannot_spoof_forwarded_for():
    assert resolve_client_ip("203.0.113.7", "1.2.3.4", PRIVATE) == "203.0.113.7"
    assert resolve_client_ip("10.0.0.5", "1.2.3.4", NONE) == "10.0.0.5"


def test_trusted_proxy_uses_forwarded_client():
    assert resolve_client_ip("172.18.0.1", "198.51.100.20", PRIVATE) == "198.51.100.20"


def test_trusted_proxy_chain_takes_right_most_untrusted_hop():
    # The client prepended a forged entry; the proxies appended the real address and their own hops.
    chain = "6.6.6.6, 198.51.100.20, 10.0.0.3"
    assert resolve_client_ip("10.0.0.2", chain, PRIVATE) == "198.51.100.20"


def test_all_hops_trusted_falls_back_to_left_most():
    assert resolve_client_ip("172.18.0.1", "192.168.1.50", PRIVATE) == "192.168.1.50"


def test_wildcard_trusts_any_peer():
    # "*" suits a proxy that overwrites the header (e.g. Railway's edge): its left-most entry is the client.
    assert resolve_client_ip("100.64.0.2", "198.51.100.20", ANY) == "198.51.100.20"
    assert resolve_client_ip("100.64.0.2", "198.51.100.20, 100.64.0.9", ANY) == "198.51.100.20"
    assert resolve_client_ip("100.64.0.2", "", ANY) == "100.64.0.2"


def test_ipv6_and_ipv4_mapped_peers():
    assert resolve_client_ip("::1", "2001:db8::1", PRIVATE) == "2001:db8::1"
    assert resolve_client_ip("::ffff:10.0.0.2", "198.51.100.20", PRIVATE) == "198.51.100.20"


def test_non_ip_values():
    assert resolve_client_ip(None, "1.2.3.4", ANY) == "unknown"
    assert resolve_client_ip("testclient", "1.2.3.4", PRIVATE) == "testclient"
    assert resolve_client_ip("10.0.0.2", "garbage, 10.0.0.3", PRIVATE) == "garbage"


def test_invalid_trusted_proxies_rejected():
    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        parse_trusted_proxies("10.0.0.0/8, not-an-ip")


def test_client_ip_reads_request(monkeypatch):
    monkeypatch.setattr(security, "_trusted_proxies", PRIVATE)

    def request(peer: str, forwarded: str) -> Request:
        return Request({"type": "http", "headers": [(b"x-forwarded-for", forwarded.encode())], "client": (peer, 1234)})

    assert client_ip(request("10.0.0.2", "198.51.100.20")) == "198.51.100.20"
    assert client_ip(request("203.0.113.7", "198.51.100.20")) == "203.0.113.7"


@pytest.mark.parametrize("env,expected", [
    ({}, ""),
    ({"RAILWAY_PROJECT_ID": "p"}, "*"),
    ({"RAILWAY_SERVICE_ID": "s", "TRUSTED_PROXIES": "10.0.0.0/8"}, "10.0.0.0/8"),
    ({"RAILWAY_ENVIRONMENT_ID": "e", "TRUSTED_PROXIES": ""}, ""),
    ({"TRUSTED_PROXIES": "*"}, "*"),
])
def test_trusted_proxies_default(monkeypatch, env, expected):
    for key in ("TRUSTED_PROXIES", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert Settings().effective_trusted_proxies == expected
