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
