import os
import pathlib
import logging
from typing import Optional

from backend.config import settings

# Optional third‑party libraries – they are imported lazily inside the relevant functions
# docx2pdf (Windows only) for DOCX → PDF
# pypdf for PDF → TXT
# Pillow + reportlab for image → PDF and TXT → PDF

logger = logging.getLogger('helix.converter')


def _is_inside_workspace(path: pathlib.Path) -> bool:
    """Ensure the given path is a child of the monitored workspace folder.
    Prevents arbitrary‑path attacks where a user could request conversion of system files.
    """
    try:
        workspace = pathlib.Path(settings.BASE_DIR).resolve()
        return workspace in path.resolve().parents or workspace == path.resolve()
    except Exception as e:
        logger.error('Workspace validation failed: %s', e)
        return False


def _build_target_path(source: pathlib.Path, target_ext: str) -> pathlib.Path:
    """Create a new file next to the source with a '_converted' suffix.
    Example: /docs/report.docx  + '.pdf'  ->  /docs/report_converted.pdf
    """
    suffix = '_converted'
    new_name = f"{source.stem}{suffix}.{target_ext}"
    return source.parent / new_name


def _convert_docx_to_pdf(source: pathlib.Path, target: pathlib.Path) -> None:
    try:
        from docx2pdf import convert
        convert(str(source), str(target))
    except Exception as e:
        raise RuntimeError(f'docx2pdf conversion failed: {e}')


def _convert_pdf_to_txt(source: pathlib.Path, target: pathlib.Path) -> None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(source))
        text = "\n\n".join(page.extract_text() or '' for page in reader.pages)
        target.write_text(text, encoding='utf-8')
    except Exception as e:
        raise RuntimeError(f'PDF to TXT conversion failed: {e}')


def _convert_image_to_pdf(source: pathlib.Path, target: pathlib.Path) -> None:
    try:
        from PIL import Image
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter

        img = Image.open(str(source))
        c = canvas.Canvas(str(target), pagesize=letter)
        width, height = letter
        img_width, img_height = img.size
        scale = min(width / img_width, height / img_height)
        img_width = img_width * scale
        img_height = img_height * scale
        x = (width - img_width) / 2
        y = (height - img_height) / 2
        c.drawImage(str(source), x, y, img_width, img_height)
        c.showPage()
        c.save()
    except Exception as e:
        raise RuntimeError(f'Image to PDF conversion failed: {e}')


def _convert_txt_to_pdf(source: pathlib.Path, target: pathlib.Path) -> None:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch

        c = canvas.Canvas(str(target), pagesize=letter)
        width, height = letter
        text = source.read_text(encoding='utf-8')
        left_margin = inch
        top_margin = height - inch
        line_height = 14
        y = top_margin
        for line in text.splitlines():
            if y < inch:
                c.showPage()
                y = top_margin
            c.drawString(left_margin, y, line)
            y -= line_height
        c.save()
    except Exception as e:
        raise RuntimeError(f'TXT to PDF conversion failed: {e}')

#Remove this if error occurs

def _convert_pdf_to_png(source: pathlib.Path, target: pathlib.Path) -> None:
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(source))
        page = pdf[0]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil()
        image.save(str(target), "PNG")

        page.close()
        pdf.close()
    except Exception as e:
        raise RuntimeError(f'PDF to PNG conversion failed: {e}')

def convert_file(source_path: str, target_format: str) -> dict:
    """Public API used by the FastAPI route.
    Returns a dict compatible with `ConvertFileResponse`.
    """
    source = pathlib.Path(source_path)
    if not source.is_file():
        return {'status': 'error', 'error': f'Source file does not exist: {source_path}'}
    # if not _is_inside_workspace(source):
    #     return {'status': 'error', 'error': 'Source file is outside the allowed workspace'}
    target_ext = target_format.lower().lstrip('.')
    target = _build_target_path(source, target_ext)
    try:
        if source.suffix.lower() == '.docx' and target_ext == 'pdf':
            _convert_docx_to_pdf(source, target)
        elif source.suffix.lower() == '.pdf' and target_ext == 'txt':
            _convert_pdf_to_txt(source, target)
        elif source.suffix.lower() == '.pdf' and target_ext == 'png':
            _convert_pdf_to_png(source, target)
        elif source.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'} and target_ext == 'pdf':
            _convert_image_to_pdf(source, target)
        elif source.suffix.lower() == '.txt' and target_ext == 'pdf':
            _convert_txt_to_pdf(source, target)
        else:
            return {'status': 'error', 'error': f'Unsupported conversion: {source.suffix} -> {target_format}'}
    except Exception as e:
        logger.exception('Conversion failed')
        return {'status': 'error', 'error': str(e)}
    return {'status': 'success', 'source_path': str(source), 'target_path': str(target)}
