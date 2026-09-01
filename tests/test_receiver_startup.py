import socket

from f1_26_split_telemetry import Receiver, Shared


def test_receiver_reports_udp_bind_failure(tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    port = blocker.getsockname()[1]
    receiver = Receiver(Shared(), port, str(tmp_path))
    try:
        receiver.start()
        assert receiver.ready.wait(2.0)
        receiver.join(2.0)
        assert receiver.startup_error is not None
        assert not receiver.is_alive()
    finally:
        receiver.running = False
        blocker.close()


def test_receiver_stops_cleanly_when_no_packets_arrive(tmp_path):
    receiver = Receiver(Shared(), 0, str(tmp_path))
    receiver.start()
    assert receiver.ready.wait(2.0)
    assert receiver.startup_error is None
    receiver.running = False
    receiver.join(2.0)
    assert not receiver.is_alive()
