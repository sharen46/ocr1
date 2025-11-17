import os
import re
import json
import time
from typing import Any, Dict, List, Tuple

import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
import pytesseract


# =========================
#   LOW-LEVEL OCR HELPERS
# =========================

def ocr_image(img: Image.Image) -> str:
    """Run Tesseract OCR on a PIL image."""
    return pytesseract.image_to_string(img)


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Try text-based extraction first (pdfplumber).
    If it fails or text is very short, fall back to OCR.
    """
    full_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text.append(page_text)
    joined = "\n".join(full_text).strip()

    # If we got reasonable text, use it
    if len(joined) > 100:
        return joined

    # Otherwise OCR the pages
    ocr_texts = []
    images = convert_from_path(pdf_path)
    for img in images:
        ocr_texts.append(ocr_image(img))
    return "\n".join(ocr_texts)


def extract_text_from_image(image_path: str) -> str:
    img = Image.open(image_path)
    return ocr_image(img)


def extract_text_from_file(path: str, ext: str) -> str:
    ext = ext.lower()
    if ext == "pdf":
        return extract_text_from_pdf(path)
    else:
        return extract_text_from_image(path)


# =========================
#   HEADER / AREA PARSING
# =========================

def extract_area_from_address(address: str) -> str:
    """
    Extract Area (e.g. 'Bangi') from Malaysian-style address:

      'NO 5, JLN 12/1, SEKSYEN 12, 43650 B.B.BANGI'
      -> 'Bangi'
    """
    if not address:
        return ""

    addr_up = address.upper()

    # Look for: <postcode> <tail...>
    m = re.search(r'\b\d{5}\b\s+([A-Z\.\s]+)', addr_up)
    if not m:
        return ""

    # Example tail: 'B.B.BANGI CASH SALE NO'
    segment = m.group(1).replace(".", " ")
    segment = re.sub(r"\s+", " ", segment).strip()
    if not segment:
        return ""

    tokens = segment.split()
    stop_words = {
        "CASH", "SALE", "NO", "PAGE", "TEL", "FAX",
        "ITEMITEM", "RM", "RINGGIT", "MALAYSIA"
    }

    area_tokens: List[str] = []
    for t in tokens:
        if t in stop_words:
            break
        area_tokens.append(t)

    if not area_tokens:
        area_tokens = tokens

    # Prefer last token with length > 2
    for t in reversed(area_tokens):
        if len(t) > 2:
            return t.title()

    return area_tokens[-1].title()


def parse_header(text: str) -> Dict[str, Any]:
    lines = text.splitlines()

    supplier_name = ""
    supplier_address_lines: List[str] = []
    doc_number = ""
    doc_date = ""
    doc_type = ""

    # ---------- Supplier Name + Address (stop before CASH SALE / INVOICE) ----------
    for i, line in enumerate(lines):
        if "SDN BHD" in line.upper():
            supplier_name = line.strip()
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    break
                if "CASH SALE" in nxt.upper() or "INVOICE" in nxt.upper():
                    break
                supplier_address_lines.append(nxt.strip())
                j += 1
            break

    # ---------- Document Type (CASH SALE / INVOICE line) ----------
    for line in lines:
        up = line.upper()
        if "CASH SALE" in up or "CASH SALES" in up or "INVOICE" in up:
            doc_type = line.strip()
            break

    # ---------- Invoice Number patterns ----------
    patterns = [
        r"CASH\s*SALE\s*No\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"INVOICE\s*NO\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"\bSGM-\d{7}\b",
        r"\bCS\d{6}\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            # If there is a capturing group (invoice no after label), use it;
            # otherwise, use the whole match (e.g. 'SGM-0001156')
            doc_number = m.group(1) if m.lastindex else m.group(0)
            break

    # ---------- Date dd/mm/yyyy ----------
    m_date = re.search(r"\d{2}/\d{2}/\d{4}", text)
    if m_date:
        doc_date = m_date.group(0)

    return {
        "supplier": {
            "name": supplier_name,
            "address": " ".join(supplier_address_lines),
        },
        "document": {
            "type": doc_type,
            "number": doc_number,
            "date": doc_date,
        },
    }


# =========================
#   ITEMS & TOTALS
# =========================

def parse_items(text: str) -> List[Dict[str, Any]]:
    """
    Parse Viva Talent 'CASH SALE' item lines.

    Example line:
      1. PCC-50KG 50KG  CEMENT COMPOSITE PCC -[ YTL:CASTLE 20.00 BAG 22.00 440.00
      6. UP-3B100M6 4" X 5.8M UPVC PIPE (SIRIM)-CS 2.00 LGTH 101.00 30% 141.40

    Structure:
      line_no. CODE DESCRIPTION qty UOM unit_price [disc%] amount
    """
    lines = text.splitlines()
    items: List[Dict[str, Any]] = []

    pat = re.compile(
        r'^\s*(?P<line_no>\d+)\.\s+'                 # 1.
        r'(?P<code>[A-Z0-9\-]+)\s+'                  # PCC-50KG
        r'(?P<desc>.+?)\s+'                          # description (lazy)
        r'(?P<qty>\d+(?:\.\d+)?)\s+'                 # 20.00
        r'(?P<uom>[A-Z]+)\s+'                        # BAG / DRUM / TIN / ...
        r'(?P<unit_price>\d{1,3}(?:,\d{3})*\.\d{2})' # 22.00
        r'(?:\s+(?P<disc>\d+%))?'                    # optional "30%"
        r'\s+(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2})\s*$'  # 440.00
    )

    def to_float(s: str) -> float:
        return float(s.replace(",", ""))

    for ln in lines:
        s = ln.strip()
        m = pat.match(s)
        if not m:
            continue
        g = m.groupdict()
        items.append({
            "line_no": int(g["line_no"]),
            "uom": g["uom"],
            "description": g["desc"].strip(),

            "qty": to_float(g["qty"]),
            "unit_price": to_float(g["unit_price"]),
            "line_total": to_float(g["amount"]),
            "item_code": g["code"],
            "disc": g["disc"] or "",
        })

    return items


def parse_totals(text: str) -> Dict[str, Any]:
    """
    Extract:
      - Total Qty (e.g. 'Total Qty 77.00')
      - Grand total from 'RINGGIT MALAYSIA ... Total 4,793.50'
      - Amount in words line
    """
    total_qty = None
    grand_total = None
    amount_in_words = ""

    # Total Qty
    m_qty = re.search(r'Total\s+Qty\s+(\d{1,3}(?:,\d{3})*\.\d{2})', text, re.IGNORECASE)
    if m_qty:
        total_qty = float(m_qty.group(1).replace(",", ""))

    # Find "RINGGIT MALAYSIA ..." line
    for line in text.splitlines():
        if "RINGGIT MALAYSIA" in line.upper():
            amount_in_words = line.strip()
            break

    # From that line, take the *last* number as grand_total
    if amount_in_words:
        nums = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', amount_in_words)
        if nums:
            grand_total = float(nums[-1].replace(",", ""))

    return {
        "total_qty": total_qty,
        "grand_total": grand_total,
        "amount_in_words": amount_in_words,
    }


# =========================
#   MAIN EXTRACTOR (ONE)
# =========================

def extract_receipt_to_object(file_path: str, ext: str) -> dict:
    """
    Extracts data from a SINGLE receipt (PDF or image)
    and returns a Python dict matching your schema for that file only.
    """
    start_time = time.time()

    # Raw text (pdfplumber first, OCR fallback)
    raw_text = extract_text_from_file(file_path, ext)

    header = parse_header(raw_text)
    items = parse_items(raw_text)
    totals = parse_totals(raw_text)

    # ---------- Basic Fields ----------
    invoice_number = header["document"].get("number")
    if not invoice_number:
        # Fallback: use file name without extension
        base = os.path.basename(file_path)
        invoice_number = os.path.splitext(base)[0] or "UNKNOWN"

    date_of_invoice = header["document"].get("date") or ""

    # ---------- Total RM ----------
    # Prefer sum of item amounts (exclude summary-like lines, though our items
    # here are already clean, we keep this logic future-proof).
    charge_items = [
        it for it in items
        if "RINGGIT MALAYSIA" not in it["description"].upper()
        and "TOTAL QTY" not in it["description"].upper()
        and " TOTAL" != it["description"].upper().strip()
    ]

    if charge_items:
        total_val = sum(it["line_total"] for it in charge_items)
        total_rm = f"{total_val:.2f}"
    elif totals.get("grand_total") is not None:
        total_rm = f'{totals["grand_total"]:.2f}'
    else:
        total_rm = ""

    # ---------- Dealer & Area ----------
    dealer_name = header["supplier"].get("name") or ""
    address = header["supplier"].get("address") or ""
    area = extract_area_from_address(address)

    # ---------- Table rows ----------
    table_rows = []
    for it in items:
        row = {
            "Product Description": it["description"],
            "Quantity": it["qty"],
            "Unit Price": f'{it["unit_price"]:.2f}',
            "Amount": f'{it["line_total"]:.2f}',
        }
        table_rows.append(row)

    # ---------- isInvoice flag ----------
    doc_type = (header["document"].get("type") or "").upper()
    is_invoice_flag = (
        "INVOICE" in doc_type
        or invoice_number.startswith("CS")
        or invoice_number.startswith("SGM")
        or invoice_number.startswith("P")
    )

    # ---------- Processing time ----------
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    processing_time_str = f"{minutes:02d}:{seconds:02d}"

    # ---------- Final object per file ----------
    single_file_data = {
        "status": True,
        "message": "File processed successfully",
        "data": {
            "Invoice Number": invoice_number,
            "Date of Invoice": date_of_invoice,
            "Total RM": total_rm,
            "Dealer Name": dealer_name,
            "Area": area,
            "table": table_rows,
            "isInvoice": is_invoice_flag,
        },
        "status_code": 200,
        "isInvoice": is_invoice_flag,
        "invoice_number": invoice_number,
        "processing_time": processing_time_str,
    }

    return single_file_data


# =========================
#   JSON WRAPPERS
# =========================

def extract_receipt_to_json(file_path: str, ext: str) -> str:
    """
    Wrapper for ONE file; returns JSON:

    {
        "status": true,
        "message": "1 out of 1 files processed",
        "data": {
            "SGM-0001156": { ... }
        }
    }
    """
    single_obj = extract_receipt_to_object(file_path, ext)
    invoice_number = single_obj.get("invoice_number") or "UNKNOWN"

    top_level = {
        "status": single_obj.get("status", False),
        "message": "1 out of 1 files processed",
        "data": {
            invoice_number: single_obj
        }
    }
    return json.dumps(top_level, indent=4, ensure_ascii=False)


def extract_multiple_receipts_to_json(files: List[Tuple[str, str]]) -> dict:
    """
    Process multiple files at once.

    files: list of (file_path, ext)

    Returns dict:

    {
      "status": true,
      "message": "2 out of 2 files processed",
      "data": {
        "SGM-0001088": {...},
        "SGM-0001156": {...}
      }
    }
    """
    results: Dict[str, dict] = {}
    processed_count = 0

    for file_path, ext in files:
        try:
            single_obj = extract_receipt_to_object(file_path, ext)
            invoice_number = single_obj.get("invoice_number") or "UNKNOWN"
            results[invoice_number] = single_obj
            processed_count += 1
        except Exception as e:
            # In case of error, still record something
            base = os.path.basename(file_path)
            invoice_number = os.path.splitext(base)[0] or "UNKNOWN"
            results[invoice_number] = {
                "status": False,
                "message": f"Error processing file: {e}",
                "data": {},
                "status_code": 500,
                "isInvoice": False,
                "invoice_number": invoice_number,
                "processing_time": "00:00",
            }

    total_files = len(files)
    top_level = {
        "status": processed_count == total_files,
        "message": f"{processed_count} out of {total_files} files processed",
        "data": results,
    }
    return top_level
