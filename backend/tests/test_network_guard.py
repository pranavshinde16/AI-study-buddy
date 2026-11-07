import socket

import pytest


def test_tests_cannot_reach_the_internet():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="not allowed in tests"):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()
