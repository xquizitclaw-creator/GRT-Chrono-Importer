"""Run: python3 -I tests/test_grt_ipc.py"""
import json
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from grt_ipc import GRTClient, parse_connect_args  # noqa: E402


class ParseConnectArgs(unittest.TestCase):
    def test_ipcport(self):
        self.assertEqual(("tcp", 32035), parse_connect_args(["x", "--ipcport", "32035"]))
        self.assertEqual(("tcp", 4000), parse_connect_args(["x", "--ipcport=4000"]))

    def test_ipcfile(self):   # GRT's Linux transport: GRTMultiPlatform passes it on Linux
        self.assertEqual(("unix", "/tmp/grt-ab.sock"), parse_connect_args(["x", "--ipcfile", "/tmp/grt-ab.sock"]))
        self.assertEqual(("unix", "/tmp/a b.sock"), parse_connect_args(["x", "--ipcfile=/tmp/a b.sock"]))

    def test_nothing_or_bad_port(self):
        self.assertIsNone(parse_connect_args(["x"]))
        self.assertIsNone(parse_connect_args(["x", "--ipcport", "abc"]))
        self.assertIsNone(parse_connect_args(["x", "--ipcfile"]))


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "no Unix sockets")
class UnixSocketClient(unittest.TestCase):
    def test_connects_and_sends_over_a_unix_socket(self):
        path = os.path.join(tempfile.mkdtemp(), "grt.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        try:
            client = GRTClient(("unix", path))
            client.connect(timeout=2.0)
            conn, _ = server.accept()
            client.send_command("Get_TabOnTop")
            self.assertEqual({"Get_TabOnTop": None}, json.loads(conn.recv(1024).decode()))
            conn.close()
            client.close()
        finally:
            server.close()
            os.remove(path)


class TcpClient(unittest.TestCase):
    def test_connects_and_sends_over_tcp(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            client = GRTClient(("tcp", server.getsockname()[1]))
            client.connect(timeout=2.0)
            conn, _ = server.accept()
            client.send_command("Get_TabOnTop")
            self.assertEqual({"Get_TabOnTop": None}, json.loads(conn.recv(1024).decode()))
            conn.close()
            client.close()
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
