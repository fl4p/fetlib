import ocrmypdf.helpers
from ocrmypdf import hookimpl
from ocrmypdf._exec import ghostscript

@hookimpl #(hookwrapper=True)
def rasterize_pdf_page(
        input_file,
        output_file,
        raster_device,
        raster_dpi:ocrmypdf.helpers.Resolution,
        pageno,
        page_dpi,
        rotation,
        filter_vector,
        stop_on_soft_error,
):

    # limit DPI to prevent insanely large images
    raster_dpi.x = min(raster_dpi.x, 600)
    raster_dpi.y = min(raster_dpi.y, 600)

    ghostscript.rasterize_pdf(
        input_file,
        output_file,
        raster_device=raster_device,
        raster_dpi=raster_dpi,
        pageno=pageno,
        page_dpi=page_dpi,
        rotation=rotation,
        filter_vector=filter_vector,
        stop_on_error=stop_on_soft_error,
    )
    return output_file

@hookimpl
def add_options(parser):
    pass
