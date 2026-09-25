from backend.app.execution.worker import _exit_when_parent_dies


class _Parent:
    def __init__(self, alive_checks: int):
        self.remaining = alive_checks

    def is_alive(self) -> bool:
        self.remaining -= 1
        return self.remaining >= 0


def test_worker_exits_once_the_server_that_spawned_it_is_gone():
    exits, naps = [], []
    _exit_when_parent_dies(_Parent(alive_checks=3), exits.append, interval=0.5, sleep=naps.append)
    assert exits == [1]  # nonzero: the run did not finish
    assert naps == [0.5, 0.5, 0.5]  # kept waiting while the parent was alive


def test_worker_exits_immediately_if_the_parent_is_already_dead():
    exits, naps = [], []
    _exit_when_parent_dies(_Parent(alive_checks=0), exits.append, sleep=naps.append)
    assert exits == [1] and naps == []
