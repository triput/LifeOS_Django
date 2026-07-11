# ==============================================================================
# File: parse_docx.py
# Description: Helper script to extract text from DOCX using python built-in XML libraries
# Component: DevOps / Utility
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
# ==============================================================================
import zipfile
import xml.etree.ElementTree as ET

def extract_docx_text(docx_path):
    with zipfile.ZipFile(docx_path) as z:
        xml_content = z.read('word/document.xml')
        root = ET.fromstring(xml_content)
        
        # Find all w:t text elements and w:p paragraph markers
        text_elements = []
        for elem in root.iter():
            if elem.tag.endswith('}t'): # w:t tag
                text_elements.append(elem.text or '')
            elif elem.tag.endswith('}p'): # w:p paragraph tag
                text_elements.append('\n')
        
        # Clean up double newlines slightly but preserve paragraphs
        raw_text = ''.join(text_elements)
        return raw_text

if __name__ == '__main__':
    try:
        text = extract_docx_text('LifeOS-SRS.docx')
        with open('LifeOS-SRS.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        print("[✓] Success: Extracted text written to LifeOS-SRS.txt")
    except Exception as e:
        print(f"[✗] Error parsing DOCX: {e}")
