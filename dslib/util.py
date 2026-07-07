import contextlib
from typing import Literal

import joblib
from tqdm import tqdm


def open_file_with_default_app(filepath):
    import subprocess, os, platform
    if platform.system() == 'Darwin':  # macOS
        subprocess.call(('open', filepath))
    elif platform.system() == 'Windows':  # Windows
        os.startfile(filepath)
    else:  # linux variants
        subprocess.call(('xdg-open', filepath))


def unique_stable(l, pop_none=False):
    d = dict(zip(l, l))
    if pop_none:
        d.pop(None, None)
    return list(d.keys())


def num_cores():
    try:
        # noinspection PyUnresolvedReferences
        return len(os.sched_getaffinity(0))
    except:
        # see https://stackoverflow.com/questions/1006289/how-to-find-out-the-number-of-cpus-using-python
        import multiprocessing
        return multiprocessing.cpu_count()


@contextlib.contextmanager
def tqdm_joblib(tqdm_object):
    """Context manager to patch joblib to report into tqdm progress bar given as argument"""

    class TqdmBatchCompletionCallback(joblib.parallel.BatchCompletionCallBack):
        def __call__(self, *args, **kwargs):
            tqdm_object.update(n=self.batch_size)
            return super().__call__(*args, **kwargs)

    old_batch_callback = joblib.parallel.BatchCompletionCallBack
    joblib.parallel.BatchCompletionCallBack = TqdmBatchCompletionCallback
    try:
        yield tqdm_object
    finally:
        joblib.parallel.BatchCompletionCallBack = old_batch_callback
        tqdm_object.close()


def run_serial(jobs):
    res = {}
    for k, fn in jobs.items():
        # print(k, '...')
        res[k] = fn() if callable(fn) else fn[0](*fn[1:])
    return res


def run_parallel(jobs, max_concurrency=256,
                 backend: Literal['threading', 'multiprocessing'] = 'multiprocessing',
                 verbose=100, **kwargs):
    if max_concurrency == 1:
        return run_serial(jobs)

    from joblib import Parallel, delayed
    with tqdm_joblib(tqdm(desc="Run Progress:", total=len(jobs))) as progress_bar:
        results = Parallel(n_jobs=min(num_cores() + 1, max_concurrency, len(jobs)), verbose=verbose, backend=backend,
                           **kwargs)(
            delayed(fn)() if callable(fn) else delayed(fn[0])(*fn[1:]) for fn in jobs.values())
    return dict(zip(jobs.keys(), results))
