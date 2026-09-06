import os
import sys
import json
from typing import Dict, Any, Optional

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:
    PdfReader = None
    PdfReadError = Exception

try:
    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError
except ImportError:
    Document = None
    PackageNotFoundError = Exception


def _result(status: str, path: str, text: str = "", error: Optional[str] = None) -> Dict[str, Any]:
    filename = os.path.basename(path)
    return {
        "status": status,
        "filename": filename,
        "path": os.path.abspath(path),
        "text": text,
        "textLength": len(text),
        "error": error
    }


import logging

logger = logging.getLogger("helix.document_processor")

_ocr_reader = None


def _get_ocr_reader():
    """Lazy initialize EasyOCR reader."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        except Exception as e:
            logger.warning(f"EasyOCR initialization failed: {e}")
            _ocr_reader = None
    return _ocr_reader


def _extract_text_from_image(img) -> str:
    """Run OCR on a PIL Image, numpy array, or file path."""
    reader = _get_ocr_reader()
    if reader is None:
        return ""
    try:
        import numpy as np
        if hasattr(img, "convert"):
            img = np.array(img.convert("RGB"))
        results = reader.readtext(img, detail=0)
        return " ".join(results).strip()
    except Exception as e:
        logger.debug(f"OCR extraction failed for image: {e}")
        return ""


def _extract_pdf(path: str) -> Dict[str, Any]:
    if PdfReader is None:
        return _result("error", path, error="pypdf is not installed")
    try:
        reader = PdfReader(path)
        pages_text = []
        for i, page in enumerate(reader.pages):
            page_content = page.extract_text()
            if page_content:
                pages_text.append(page_content.strip())
        
        full_text = "\n\n".join(pages_text).strip()
        
        # Fast path: If digital text was found with meaningful length, return it
        if full_text and len(full_text) >= 40:
            return _result("success", path, text=full_text)
            
        # Fallback to OCR for scanned / image-only PDFs
        ocr_pages_text = []
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(path)
            try:
                for page in pdf:
                    try:
                        # Render page at 2x resolution for clean OCR accuracy
                        pil_image = page.render(scale=2.0).to_pil()
                        page_text = _extract_text_from_image(pil_image)
                        if page_text:
                            ocr_pages_text.append(page_text)
                    finally:
                        page.close()
            finally:
                pdf.close()
        except Exception as ocr_err:
            logger.debug(f"pypdfium2 PDF OCR failed: {ocr_err}")
            # Fallback to embedded image extraction in pypdf
            for page in reader.pages:
                for img_file in getattr(page, "images", []):
                    try:
                        from PIL import Image
                        import io
                        pil_img = Image.open(io.BytesIO(img_file.data))
                        img_text = _extract_text_from_image(pil_img)
                        if img_text:
                            ocr_pages_text.append(img_text)
                    except Exception:
                        continue
                        
        ocr_text = "\n\n".join(ocr_pages_text).strip()
        if ocr_text:
            return _result("success", path, text=ocr_text)
            
        if full_text:
            return _result("success", path, text=full_text)
            
        return _result("empty", path)
    except PdfReadError as e:
        return _result("error", path, error=f"PDF read error: {e}")
    except Exception as e:
        return _result("error", path, error=f"Failed to read PDF: {e}")


def _extract_docx(path: str) -> Dict[str, Any]:
    if Document is None:
        return _result("error", path, error="python-docx is not installed")
    try:
        doc = Document(path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        
        # Also extract table text
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
                    
        full_text = "\n\n".join(paragraphs).strip()
        if not full_text:
            return _result("empty", path)
        return _result("success", path, text=full_text)
    except PackageNotFoundError as e:
        return _result("error", path, error=f"Invalid docx package: {e}")
    except Exception as e:
        return _result("error", path, error=f"Failed to read docx: {e}")


def _extract_txt(path: str) -> Dict[str, Any]:
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read().strip()
                if not text:
                    return _result("empty", path)
                return _result("success", path, text=text)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return _result("error", path, error=f"Failed to read text file: {e}")
            
    return _result("error", path, error="Could not decode text file with standard encodings")


def _extract_image(path: str) -> Dict[str, Any]:
    """Extract text from standalone images (.png, .jpg, .jpeg, .webp, .bmp, .tiff) using OCR."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            text = _extract_text_from_image(img)
            if not text:
                return _result("empty", path)
            return _result("success", path, text=text)
    except Exception as e:
        return _result("error", path, error=f"Failed to process image: {e}")


EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
    ".md": _extract_txt,
    ".log": _extract_txt,
    ".csv": _extract_txt,
    ".png": _extract_image,
    ".jpg": _extract_image,
    ".jpeg": _extract_image,
    ".webp": _extract_image,
    ".bmp": _extract_image,
    ".tiff": _extract_image,
}


def extract_text(path: str) -> Dict[str, Any]:
    """Extract text from supported document formats."""
    if not os.path.exists(path):
        return _result("error", path, error="File does not exist")
        
    ext = os.path.splitext(path)[1].lower()
    extractor = EXTRACTORS.get(ext)
    if not extractor:
        return _result("unsupported", path, error=f"Unsupported file format: {ext}")
        
    return extractor(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "error": "Missing file path argument"}))
        sys.exit(1)
        
    file_path = sys.argv[1]
    result = extract_text(file_path)
    print(json.dumps(result))
