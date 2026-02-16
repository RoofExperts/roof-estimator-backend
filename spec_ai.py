import pdfplumber
import openai
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def analyze_spec_text(spec_text):
    prompt = f"""
    You are a commercial roofing specification analyzer.

    Extract structured roofing system information from the following spec.

    Return JSON with:
    - roof_system_type
    - membrane_type
    - attachment_method
    - insulation_type
    - insulation_thickness
    - manufacturer
    - fastener_density
    - special_requirements

    Specification:
    {spec_text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract roofing system specs."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content
