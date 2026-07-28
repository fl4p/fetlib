import pandas as pd

import dslib.pdf.parse as parse
import dslib.pdf.tabular as tabular


def _df(source):
    df = pd.DataFrame([['x']])
    df.index.name = source
    return df


def test_tabula_unavailable_skips_web_and_uses_cli(monkeypatch):
    monkeypatch.setattr(tabular, 'tabula_is_running', lambda: False)

    def unexpected_browser(_path):
        raise AssertionError('unavailable web backend must not be called')

    monkeypatch.setattr(tabular, 'tabula_browser', unexpected_browser)
    monkeypatch.setattr(parse, 'tabula_read_pdf_cached',
                        lambda *_args, **_kwargs: [_df('raw_cli')])

    dfs = parse.tabula_pdf_dataframes('fixture.pdf')

    assert len(dfs) == 1
    assert dfs[0].index.name == 'tabula_cli_guess'


def test_tabula_cli_does_not_overwrite_web_provenance(monkeypatch):
    monkeypatch.setattr(tabular, 'tabula_is_running', lambda: True)
    monkeypatch.setattr(tabular, 'tabula_browser',
                        lambda _path: [_df('tabula_web_original')])
    monkeypatch.setattr(parse, 'tabula_read_pdf_cached',
                        lambda *_args, **_kwargs: [_df('raw_cli')])

    dfs = parse.tabula_pdf_dataframes('fixture.pdf')

    assert [df.index.name for df in dfs] == [
        'tabula_web_original',
        'tabula_cli_guess',
    ]


def test_tabula_probe_treats_connection_failure_as_unavailable(monkeypatch):
    def connection_failure(*_args, **_kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(tabular.socket, 'create_connection', connection_failure)
    assert tabular.tabula_is_running() is False


def test_tabula_probe_only_requires_listening_socket(monkeypatch):
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def listening(address, timeout):
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(tabular.socket, 'create_connection', listening)
    assert tabular.tabula_is_running() is True
    assert calls == [(('127.0.0.1', 8080), 0.5)]
