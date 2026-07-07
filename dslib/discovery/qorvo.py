from dslib.discovery import download_parts_list


async def qorvo_sic_fets():
    # TODO https://www.qorvo.com/products/discrete-transistors/sic-jfets
    fn = await download_parts_list(
        'qorvo',
        url="https://www.qorvo.com/products/discrete-transistors/sic-fets",
        fn_ext='xlsx',
        click='a.pst-export',
    )

    raise NotImplementedError()

    # u =
