"""apps/tabula_watchdog.py -- the decision loop, driven with injected effects.

The real restart kills a GUI app, so what can be tested is the part that decides:
consecutive-failure counting, reset on recovery, and the engage gate. Per the guard
checklist, the important assertions are the anti-monotone ones -- a probe that CANNOT run
counts as unhealthy, and a watchdog started when Tabula was never running refuses to
become the thing that launches it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from apps.tabula_watchdog import probe, run_loop  # noqa: E402


def _drive(probe_results, threshold=2):
    """Run the loop over a scripted probe sequence; return restart tick indices."""
    seq = list(probe_results)
    restarts, tick = [], [0]

    def probe_fn():
        return seq[tick[0] - 1]

    def keep_running():
        return tick[0] < len(seq)

    def sleep_fn(_):
        tick[0] += 1

    run_loop(probe_fn, lambda: restarts.append(tick[0]), keep_running, sleep_fn,
             interval=0, threshold=threshold, log=lambda m: None)
    return restarts


def test_restarts_after_threshold_consecutive_failures():
    assert _drive([True, False, False, True]) == [3]


def test_single_blip_does_not_restart():
    """One failed probe between healthy ones is a blip, not a wedge. Restarting on every
    blip would bounce a healthy server under load -- the opposite of the goal."""
    assert _drive([True, False, True, False, True]) == []


def test_recovery_resets_the_counter():
    # fail, ok, fail, fail -> the first failure must not count toward the later pair
    assert _drive([False, True, False, False]) == [4]


def test_repeated_wedges_each_get_a_restart():
    assert _drive([False, False, True, False, False]) == [2, 5]


def test_loop_exits_when_watched_process_dies():
    calls = []

    def keep_running():
        calls.append(1)
        return len(calls) < 3

    run_loop(lambda: True, lambda: None, keep_running, lambda s: None,
             interval=0, threshold=2, log=lambda m: None)
    assert len(calls) == 3  # checked each cycle; loop ended when it said stop


def test_unevaluable_probe_reads_as_unhealthy(monkeypatch):
    """The anti-monotone case: requests being unimportable/raising must count as DOWN.
    A probe that answers 'fine' when it cannot ask is the classic false PASS."""
    import builtins
    real_import = builtins.__import__

    def no_requests(name, *a, **kw):
        if name == 'requests':
            raise ImportError('requests unavailable')
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, '__import__', no_requests)
    assert probe() is False


def test_engage_gate_refuses_when_tabula_was_never_running(monkeypatch):
    """Started on a machine where Tabula is not in use, the watchdog must refuse rather
    than launch it -- the pipeline works without the GUI server via the CLI fallback,
    and a monitor's job is to keep something alive, not to decide it should exist."""
    import apps.tabula_watchdog as W
    monkeypatch.setattr(W, 'probe', lambda *a, **kw: False)
    monkeypatch.setattr(W, 'app_pid', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['tabula_watchdog.py'])
    assert W.main() == 1


def test_raising_restart_does_not_kill_the_loop():
    """Reviewer finding: main() catches only KeyboardInterrupt and nothing supervises
    the watchdog, so an uncaught OSError from restart() ended it silently -- the
    supervisor failing exactly the way it exists to prevent. It must log and keep
    watching, and a later wedge must still get a restart attempt."""
    attempts = []

    def bad_then_good_restart():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError('open -a failed')

    seq = [False, False, True, False, False]  # wedge, recover, wedge again
    tick = [0]
    run_loop(lambda: seq[tick[0] - 1],
             bad_then_good_restart,
             lambda: tick[0] < len(seq),
             lambda _: tick.__setitem__(0, tick[0] + 1),
             interval=0, threshold=2, log=lambda m: None)
    assert len(attempts) == 2, 'loop died on the raising restart instead of continuing'
