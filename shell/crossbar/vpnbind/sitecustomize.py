"""Loaded by Crossbar's own Python helpers that use the VPN (torrent search plugins, the leak tests):
their internet connections leave from the VPN's own address (CROSSBAR_VPN_SRC), which split
tunneling routes through the tunnel directly. Local and home-network addresses are left alone."""
import ipaddress
import os
import socket

_SRC = os.environ.get("CROSSBAR_VPN_SRC")
_LOCAL = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12", "169.254.0.0/16", "0.0.0.0/8")]


def _wants(sock, addr):
    try:
        if sock.family != socket.AF_INET or not isinstance(addr, tuple):
            return False
        ip = ipaddress.ip_address(addr[0])
        return not any(ip in n for n in _LOCAL) and sock.getsockname()[1] == 0
    except (ValueError, OSError):
        return False


if _SRC:
    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex

    def connect(self, addr):
        if _wants(self, addr):
            try:
                self.bind((_SRC, 0))
            except OSError:
                pass
        return _connect(self, addr)

    def connect_ex(self, addr):
        if _wants(self, addr):
            try:
                self.bind((_SRC, 0))
            except OSError:
                pass
        return _connect_ex(self, addr)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
