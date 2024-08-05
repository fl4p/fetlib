def mfr_tag(mnf: str):
    mnf = mnf.lower()
    for tag, prefix in dict(infineon='infineon', ti='texas instruments', ao='alpha & omega', nxp=('nxp', 'nexperia'),
                            st='stmicroelectronics', toshiba='toshiba', vishay='vishay', diodes='diodes inc',
                            diotec='diotec', rohm='rohm', fairchild='fairchild', good_ark='good-ark',
                            mcc=('micro commercial', 'mcc')
            , renesas='renesas', ts='taiwan semiconductor', panjit='panjit',
                            apm='a power microelectronics',
                            jscj='jiangsu changjing',
                            slkor='slkor',
                            wuxi='wuxi unigroup micro',
                            winsok='winsok',

                            ).items():
        if not isinstance(prefix, tuple):
            prefix = (prefix,)
        for p in prefix:
            if mnf.startswith(prefix):
                return tag
    return mnf.replace(' ', '_')
