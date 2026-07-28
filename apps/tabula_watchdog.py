"""Keep the Tabula GUI server alive under sustained parse load.

WHY. dslib/pdf/tabular.py drives the Tabula app's HTTP server at 127.0.0.1:8080 as a
table extractor. Under a full-corpus sweep (2026-07-28) the app wedged twice, each time
after ~2 h of sustained load: first intermittent 500s, then no response at all -- while
`pgrep Tabula.app` still showed it alive, so process liveness is NOT the health signal,
the HTTP probe is. Every affected part then burned backoff retries before falling to the
slower CLI jar, and the sweep's failure count climbed until a manual restart. A restart
takes ~12-15 s and returned failures to background rate both times; this automates it.

WHAT IT DOES, and deliberately no more:

  * probes GET / every --interval seconds; a probe that CANNOT be evaluated (timeout,
    connection refused, requests missing) counts as UNHEALTHY -- a broken probe must
    never read as a healthy server;
  * after --threshold consecutive failures, kills the Tabula.app JavaAppLauncher process
    (never the tabula-java CLI jars, which match a different command line) and relaunches
    via `open -a`;
  * ONLY manages a server that was reachable (or whose app was running) when the watchdog
    started. If Tabula was not in use, this must not decide to launch it -- the pipeline
    works without it via the CLI fallback. --force overrides for bring-up.
  * exits when the process given by --watch-pid exits, so a sweep can tie the watchdog to
    its own lifetime and leave nothing behind.

    python3 apps/tabula_watchdog.py --watch-pid 12345      # scoped to a sweep
    python3 apps/tabula_watchdog.py                        # until Ctrl-C
    python3 apps/tabula_watchdog.py --once                 # single probe, report, exit

apps/reparse_all.py starts one automatically (see --no-tabula-watchdog there).
"""
import argparse
import os
import subprocess
import sys
import time

TABULA_URL = 'http://127.0.0.1:8080/'
# The GUI app's launcher binary. The CLI fallback jars run as `java ... tabula-1.0.5-jar-
# with-dependencies.jar` and MUST NOT match -- killing those aborts in-flight extractions.
APP_PATTERN = 'Tabula.app/Contents/MacOS/JavaAppLauncher'
APP_PATH = '/Applications/Tabula.app'


def probe(timeout=10.0):
    """True only for a confirmed-healthy server. Every failure mode -- refused, timed
    out, requests not importable -- is False; absence of evidence is not health.

    10 s, not 5: under 8-way sweep load a BUSY-but-alive server can take >5 s to answer
    GET /, and with threshold=2 a 5 s timeout turned one busy minute into a restart of a
    server that was working (observed on the integration smoke test). The discriminator
    for a real wedge is not answering at all, which 10 s still catches in one interval.
    """
    try:
        import requests
        return requests.get(TABULA_URL, timeout=timeout).status_code == 200
    except Exception:
        return False


def app_pid():
    try:
        out = subprocess.run(['pgrep', '-f', APP_PATTERN],
                             capture_output=True, text=True, timeout=10).stdout.split()
        return int(out[0]) if out else None
    except Exception:
        return None


def restart(log=print, come_up_wait=60):
    pid = app_pid()
    if pid is not None:
        log('killing wedged Tabula (pid %d)' % pid)
        subprocess.run(['kill', str(pid)], capture_output=True)
        time.sleep(3)
        if app_pid() == pid:
            subprocess.run(['kill', '-9', str(pid)], capture_output=True)
            time.sleep(2)
    log('relaunching %s' % APP_PATH)
    subprocess.run(['open', '-a', APP_PATH], capture_output=True)
    deadline = time.time() + come_up_wait
    while time.time() < deadline:
        time.sleep(3)
        if probe():
            log('tabula serving again')
            return True
    # Report the truth rather than assuming the relaunch worked; the loop keeps probing
    # and will try again, so a failed come-up is a logged fact, not a silent success.
    log('tabula did NOT come up within %ds' % come_up_wait)
    return False


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_loop(probe_fn, restart_fn, keep_running_fn, sleep_fn,
             interval=30, threshold=2, log=print):
    """The decision loop, with every effect injectable so tests can drive it.

    threshold consecutive UNHEALTHY probes -> restart; any healthy probe resets the
    count. keep_running_fn() False ends the loop (watched process exited / Ctrl-C).
    """
    fails = 0
    while keep_running_fn():
        sleep_fn(interval)
        if probe_fn():
            fails = 0
            continue
        fails += 1
        log('probe failed (%d/%d)' % (fails, threshold))
        if fails >= threshold:
            # A raising restart must not kill the loop. main() catches only
            # KeyboardInterrupt, and reparse_all deliberately does not supervise this
            # process -- so an uncaught OSError here would end the watchdog silently and
            # the rest of a multi-hour sweep would run unguarded: the supervisor failing
            # the exact way it exists to prevent. Log it, keep the counter, keep probing;
            # the next threshold crossing tries again.
            try:
                restart_fn()
            except Exception as e:
                log('restart FAILED: %s: %s -- still watching' % (type(e).__name__, e))
            fails = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--watch-pid', type=int, default=None,
                    help='exit when this process exits (tie the watchdog to a sweep)')
    ap.add_argument('--interval', type=float, default=30)
    ap.add_argument('--threshold', type=int, default=2)
    ap.add_argument('--once', action='store_true', help='single probe, report, exit')
    ap.add_argument('--force', action='store_true',
                    help='engage even if Tabula was not running at startup')
    args = ap.parse_args()

    def log(msg):
        print('[tabula-watchdog %s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)

    if args.once:
        ok = probe()
        print('tabula: %s (app pid: %s)' % ('UP' if ok else 'DOWN', app_pid()))
        return 0 if ok else 1

    if not (probe() or app_pid() is not None or args.force):
        log('tabula is not running and --force not given; refusing to become the thing '
            'that launches it. The pipeline works without it via the CLI fallback.')
        return 1

    def keep_running():
        return args.watch_pid is None or pid_alive(args.watch_pid)

    log('watching %s (interval %gs, threshold %d%s)'
        % (TABULA_URL, args.interval, args.threshold,
           ', tied to pid %d' % args.watch_pid if args.watch_pid else ''))
    try:
        run_loop(probe, lambda: restart(log), keep_running, time.sleep,
                 interval=args.interval, threshold=args.threshold, log=log)
    except KeyboardInterrupt:
        pass
    log('exiting')
    return 0


if __name__ == '__main__':
    sys.exit(main())
