import os.path


def get_datasheets_path(mfr=None, mpn=None):
    p = os.path.realpath(os.path.dirname(__file__) + '/../datasheets')
    if mpn is None:
        return p
    return os.path.join(p, mfr, mpn + '.pdf')


def mfr_tag(mnf: str):
    mnf = mnf.lower()
    for tag, prefix in dict(
            infineon=('infineon', 'international rectifier'),
            ti='texas instruments', ao='alpha & omega', nxp=('nxp', 'nexperia'),
            st='stmicroelectronics', toshiba='toshiba', vishay='vishay', diodes='diodes inc',
            diotec='diotec', rohm='rohm', fairchild='fairchild', good_ark='good-ark',
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
            littelfuse='littelfuse',

    ).items():
        if not isinstance(prefix, tuple):
            prefix = (prefix,)
        for p in prefix:
            if mnf.startswith(p):
                return tag
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
