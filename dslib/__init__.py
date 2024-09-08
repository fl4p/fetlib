import math
import os.path


def get_datasheets_path(mfr=None, mpn=None):
    p = os.path.realpath(os.path.dirname(__file__) + '/../datasheets')
    if mpn is None:
        return p
    return os.path.join(p, mfr, mpn + '.pdf')


mfrs = dict(
    infineon=('infineon', 'international rectifier'),
    ti='texas instruments', ao='alpha & omega', nxp=('nxp', 'nexperia'),
    st='stmicroelectronics', toshiba='toshiba', vishay='vishay', diodes='diodes inc',
    diotec='diotec', rohm='rohm',
    good_ark='good-ark',
    mcc=('micro commercial', 'mcc')
    , renesas='renesas',
    ts='taiwan semiconductor',
    panjit='panjit',
    apm='a power microelectronics',
    jscj='jiangsu changjing',
    slkor='slkor',
    wuxi='wuxi unigroup micro',
    winsok='winsok',
    epc_space='epc space',
    goford='goford',
    littelfuse=('littelfuse', 'ixys'),
    onsemi=('onsemi', 'fairchild'),
    analog_power='analog power',
    yageo_xsemi='yageo_xsemi',

)


def mfr_tag(mnf: str, raise_unknown=False):
    mnf = mnf.lower()
    for tag, prefix in mfrs.items():
        if not isinstance(prefix, tuple):
            prefix = (prefix,)
        for p in prefix:
            if mnf.startswith(p):
                return tag
    if mnf in mfrs:
        return mnf

    if raise_unknown:
        raise ValueError(f'unknown mfr: {mnf}')

    return mnf.replace(' ', '_')


def get_logger(verbose: bool = False):
    import logging

    # log_format = '%(asctime)s %(levelname)-6s [%(filename)s:%(lineno)d] %(message)s'
    log_format = '%(asctime)s %(levelname)s [%(module)s] %(message)s'
    if verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level, format=log_format, datefmt='%H:%M:%S')
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    return logger


def round_to_n(x, n):
    # if isinstance(x, tuple):
    #    return '[%s]' % ', '.join(map(str, map(partial(round_to_n, n=n), x)))

    if isinstance(x, str) or not math.isfinite(x) or not x:
        return x

    try:
        f = round(x, -int(math.floor(math.log10(abs(x)))) + (n - 1))
        if isinstance(f, float) and f.is_integer():
            return int(f)
        return f
    except ValueError as e:
        print('error', x, n, e)
        raise e


class dotdict(dict):
    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError as e:
            raise AttributeError(str(e))  # from e

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
    # __getstate__ == dict.__getstate__

    # __hasattr__ = dict.__contains__
