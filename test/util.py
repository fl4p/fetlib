def pixmap_to_pil(pixmap):
    """Write to image file using Pillow.

    Args are passed to Pillow's Image.save method, see their documentation.
    Use instead of save when other output formats are desired.
    """
    try:
        from PIL import Image
    except ImportError:
        print("PIL/Pillow not installed")
        raise

    cspace = pixmap.colorspace
    if cspace is None:
        mode = "L"
    elif cspace.n == 1:
        mode = "L" if pixmap.alpha == 0 else "LA"
    elif cspace.n == 3:
        mode = "RGB" if pixmap.alpha == 0 else "RGBA"
    else:
        mode = "CMYK"

    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
