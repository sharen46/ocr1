# Receipt to JSON Web App

This is a simple Flask web app that lets you upload a receipt (PDF or image) and returns the extracted data in JSON format.

## Features

- Upload button for PDF / JPG / PNG
- Extracts text using:
  - `pdfplumber` for text-based PDFs
  - `Tesseract OCR` (via `pytesseract` + `pdf2image`/`Pillow`) for images or image-based PDFs
- Parses:
  - Supplier info
  - Document info (type, number, date, terms)
  - Line items
  - Totals
- Shows the JSON result in the browser.

## 1. Prerequisites

### Python

Make sure you have **Python 3.9+** installed.

### System dependencies

Because we are doing OCR and PDF → image conversion, you need:

1. **Tesseract OCR**
2. **Poppler**

Search:
- "Install Tesseract Windows" or "Install Tesseract macOS / Linux"
- "Install Poppler Windows" or use `brew install poppler` on macOS, `apt install poppler-utils` on Ubuntu.

After installing Tesseract, if needed, configure `pytesseract.pytesseract.tesseract_cmd` to point to the Tesseract executable path (Windows).

## 2. How to run in VS Code

1. **Unzip the project** somewhere, for example: `C:\code\receipt_app`.

2. **Open VS Code** → `File` → `Open Folder...` → select `receipt_app`.

3. **Create & activate a virtual environment** (inside VS Code terminal):

   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS / Linux:
   # source venv/bin/activate
   ```

4. **Install Python packages**:

   ```bash
   pip install -r requirements.txt
   ```

5. **Run the Flask app**:

   ```bash
   python app.py
   ```

6. Open your browser and go to:

   ```
   http://127.0.0.1:5000/
   ```

7. Use the **upload button** to select a receipt file (PDF or image).  
   Click **"Upload & Extract"**.  
   The parsed JSON result will appear on the page.

## 3. Notes

- The regex patterns in `receipt_extractor.py` are tuned for a particular receipt layout. You may need to adjust them for your real data.
- Check the `raw_text_preview` field in the JSON output to see what the OCR/text-extraction actually looks like and then tweak the parsing rules.
