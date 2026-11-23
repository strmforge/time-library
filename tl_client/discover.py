"""Finding the server on the local network.

Most people's routers hand the NAS a new address now and then. When the server
can't be reached for a while, the client looks for it on this computer's own
home network: every address there, on the server's port, asking "who are you"
(the public health check, which answers with the server's id). It moves over
only to the server it was paired with: same id, and the token still works
there. It never talks to a server it wasn't paired with.

This needs nothing from the NAS's network setup (no broadcast, no host
networking): an ordinary published port is enough.

Only home-network ranges (10.x, 172.16-31.x, 192.168.x) are looked at, one /24
per local address, never the internet.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Iterable
from urllib.parse import urlsplit

DEFAULT_PORT = 9850
CONNECT_TIMEOUT = 0.4
HEALTH_TIMEOUT = 2.0
WORKERS = 64
MAX_HOSTS = 1024  # at most four /24 networks per search
SEARCH_SECONDS = 15.0  # a whole search, however the networks behave

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# Home networks only (RFC 1918). Not other "private" ranges: 198.18.0.0/15 is where
# proxy tools put their virtual network card, 100.64.0.0/10 is carrier or VPN space.
HOME_RANGES = tuple(ipaddress.IPv4Network(block) for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _private(address: str) -> ipaddress.IPv4Address | None:
    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError:
        return None
    return ip if any(ip in block for block in HOME_RANGES) else None


def local_addresses(towards: Iterable[str] = ()) -> list[ipaddress.IPv4Address]:
    """This computer's own private IPv4 addresses (no packet is sent to find them)."""
    found: list[ipaddress.IPv4Address] = []
    targets = [*towards, "192.168.1.1", "10.0.0.1", "172.16.0.1", "8.8.8.8"]
    for target in targets:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((target, 9))  # picks the interface that would be used; sends nothing
                ip = _private(probe.getsockname()[0])
        except OSError:
            continue
        if ip and ip not in found:
            found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = _private(info[4][0])
            if ip and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def home_networks(server_url: str = "") -> list[ipaddress.IPv4Network]:
    """The /24 networks to look in: the one the server was last seen in first, then this computer's own."""
    towards = []
    networks: list[ipaddress.IPv4Network] = []
    host = urlsplit(server_url).hostname if server_url else None
    last = _private(host or "")
    if last:
        towards.append(str(last))
        networks.append(ipaddress.IPv4Network(f"{last}/24", strict=False))
    for ip in local_addresses(towards):
        network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        if network not in networks:
            networks.append(network)
    return networks[: MAX_HOSTS // 256]


def _open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _ask_health(url: str) -> dict | None:
    try:
        with _DIRECT.open(url.rstrip("/") + "/api/v1/health", timeout=HEALTH_TIMEOUT) as response:
            body = json.loads(response.read(4096))
    except (OSError, ValueError):
        return None
    if isinstance(body, dict) and body.get("ok") and isinstance(body.get("server_id"), str):
        return body
    return None


def health(url: str) -> dict | None:
    """What a Time Library server at url says about itself, or None. Never waits longer than a few
    seconds: something that takes the connection and then trickles (a proxy's virtual network card)
    is given up on, not waited for."""
    answer: list[dict | None] = [None]
    asker = threading.Thread(target=lambda: answer.__setitem__(0, _ask_health(url)), daemon=True, name="tl-health")
    asker.start()
    asker.join(HEALTH_TIMEOUT + 1.0)
    return answer[0] if not asker.is_alive() else None


def find_servers(networks: Iterable[ipaddress.IPv4Network], ports: Iterable[int] | None = None,
                 server_id: str = "") -> list[dict[str, str]]:
    """Time Library servers answering in these networks: [{"url", "server_id"}], those with server_id first."""
    ports = tuple(ports) if ports else (DEFAULT_PORT,)
    hosts = []
    for network in networks:
        hosts.extend(str(host) for host in (network.hosts() if network.prefixlen < 32 else [network.network_address]))
    hosts = list(dict.fromkeys(hosts))[:MAX_HOSTS]
    candidates = [(host, port) for port in dict.fromkeys(ports) for host in hosts]
    deadline = time.monotonic() + SEARCH_SECONDS
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        jobs = {pool.submit(_open, *pair): pair for pair in candidates}
        done, _ = wait(jobs, timeout=max(0.0, deadline - time.monotonic()))
        open_ones = [jobs[job] for job in done if job.result()]
        asks = {pool.submit(health, f"http://{host}:{port}"): f"http://{host}:{port}" for host, port in open_ones}
        done, _ = wait(asks, timeout=max(0.0, deadline - time.monotonic()))
        found = [{"url": asks[job], "server_id": job.result()["server_id"]} for job in done if job.result()]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a stuck address is left behind, never waited for
    found.sort(key=lambda item: (item["server_id"] != server_id, item["url"]))
    return found


def find_again(server_url: str, server_id: str, networks: Iterable[ipaddress.IPv4Network] | None = None) -> str:
    """The new address of the server this computer was paired with, or '' if it isn't on the home network."""
    try:
        port = urlsplit(server_url).port or DEFAULT_PORT
    except ValueError:
        port = DEFAULT_PORT
    networks = home_networks(server_url) if networks is None else list(networks)
    for item in find_servers(networks, (port, DEFAULT_PORT), server_id):
        if item["server_id"] == server_id and item["url"] != server_url.rstrip("/"):
            return item["url"]
    return ""
