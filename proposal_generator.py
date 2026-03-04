"""
Proposal PDF Generator for Roof Experts
Generates professional commercial roofing bid proposals.

Pages:
  1. Project Information & Roofing System (always included)
  2. Metal Roofing System (optional - standing seam, R-panels, etc.)
  3. Wall Panels / Metal Siding / Architectural Metals (optional)
  4. Awnings / Canopies (optional)
  5. About Roof Experts (always included)
"""

import io
import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas


# ── Brand Colors ──────────────────────────────────────────────
BRAND_BLUE = HexColor("#1e3a5f")
BRAND_BLUE_LIGHT = HexColor("#2d5a8e")
BRAND_ACCENT = HexColor("#c8102e")
BRAND_GRAY = HexColor("#4a4a4a")
BRAND_GRAY_LIGHT = HexColor("#f5f5f5")
BRAND_GOLD = HexColor("#b8860b")
TABLE_HEADER_BG = HexColor("#1e3a5f")
TABLE_ALT_ROW = HexColor("#f0f4f8")
TABLE_BORDER = HexColor("#d0d5dd")


# ── Custom Styles ─────────────────────────────────────────────
def get_custom_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='ProposalTitle',
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=28,
        textColor=BRAND_BLUE,
        alignment=TA_LEFT,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name='ProposalSubtitle',
        fontName='Helvetica',
        fontSize=14,
        leading=18,
        textColor=BRAND_GRAY,
        alignment=TA_LEFT,
        spaceAfter=20,
    ))

    styles.add(ParagraphStyle(
        name='SectionHeading',
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=BRAND_BLUE,
        spaceBefore=10,
        spaceAfter=4,
        borderWidth=0,
        borderPadding=0,
    ))

    styles.add(ParagraphStyle(
        name='SubHeading',
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=BRAND_BLUE_LIGHT,
        spaceBefore=6,
        spaceAfter=2,
    ))

    styles.add(ParagraphStyle(
        name='BodyText2',
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=BRAND_GRAY,
        alignment=TA_JUSTIFY,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name='SmallText',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=BRAND_GRAY,
    ))

    styles.add(ParagraphStyle(
        name='TableHeader',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=white,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name='TableCell',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=BRAND_GRAY,
    ))

    styles.add(ParagraphStyle(
        name='TableCellBold',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=BRAND_BLUE,
    ))

    styles.add(ParagraphStyle(
        name='TotalLine',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=BRAND_BLUE,
        alignment=TA_RIGHT,
        spaceBefore=8,
    ))

    styles.add(ParagraphStyle(
        name='PageTitle',
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=26,
        textColor=BRAND_BLUE,
        alignment=TA_LEFT,
        spaceAfter=12,
    ))

    styles.add(ParagraphStyle(
        name='DisclaimerText',
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=10,
        textColor=BRAND_GRAY,
        alignment=TA_LEFT,
    ))

    return styles


# ── Header / Footer ──────────────────────────────────────────
class ProposalTemplate:
    """Draws consistent header and footer on every page."""

    def __init__(self, company_info):
        self.company = company_info
        self.page_count = 0

    def header_footer(self, canvas_obj, doc):
        self.page_count += 1
        canvas_obj.saveState()
        w, h = letter

        # ── Header bar ──
        canvas_obj.setFillColor(BRAND_BLUE)
        canvas_obj.rect(0, h - 60, w, 60, fill=1, stroke=0)

        # Company name
        canvas_obj.setFillColor(white)
        canvas_obj.setFont("Helvetica-Bold", 18)
        canvas_obj.drawString(0.75 * inch, h - 38, self.company.get("name", "ROOF EXPERTS"))

        # Tagline
        canvas_obj.setFont("Helvetica", 9)
        canvas_obj.drawString(0.75 * inch, h - 52, self.company.get("tagline", "Commercial Roofing Specialists"))

        # Contact info right side
        canvas_obj.setFont("Helvetica", 8)
        right_x = w - 0.75 * inch
        canvas_obj.drawRightString(right_x, h - 30, self.company.get("phone", ""))
        canvas_obj.drawRightString(right_x, h - 42, self.company.get("email", ""))
        canvas_obj.drawRightString(right_x, h - 54, self.company.get("website", ""))

        # ── Accent line under header ──
        canvas_obj.setStrokeColor(BRAND_ACCENT)
        canvas_obj.setLineWidth(3)
        canvas_obj.line(0, h - 62, w, h - 62)

        # ── Footer ──
        canvas_obj.setStrokeColor(TABLE_BORDER)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(0.75 * inch, 45, w - 0.75 * inch, 45)

        canvas_obj.setFillColor(BRAND_GRAY)
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.drawString(0.75 * inch, 32,
            f"{self.company.get('name', 'Roof Experts')}  |  {self.company.get('address', '')}")
        canvas_obj.drawRightString(w - 0.75 * inch, 32,
            f"Page {self.page_count}")

        # License / insurance line
        license_text = self.company.get("license", "")
        if license_text:
            canvas_obj.drawCentredString(w / 2, 20, license_text)

        canvas_obj.restoreState()


# ── Table Helpers ─────────────────────────────────────────────
def make_styled_table(headers, rows, col_widths=None):
    """Create a professionally styled table."""
    styles = get_custom_styles()

    header_row = [Paragraph(h, styles['TableHeader']) for h in headers]
    data = [header_row]

    for row in rows:
        data.append([Paragraph(str(cell), styles['TableCell']) for cell in row])

    if col_widths is None:
        col_widths = [None] * len(headers)

    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_commands = [
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, TABLE_BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
    ]

    # Alternating row colors
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_commands.append(('BACKGROUND', (0, i), (-1, i), TABLE_ALT_ROW))

    table.setStyle(TableStyle(style_commands))
    return table


def make_total_row_table(label, amount, width=6.5 * inch):
    """Create a right-aligned total row."""
    data = [[label, amount]]
    t = Table(data, colWidths=[width - 1.5 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'RIGHT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (-1, -1), BRAND_BLUE),
        ('LINEABOVE', (0, 0), (-1, 0), 1.5, BRAND_BLUE),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
    ]))
    return t


# ── Page Builders ─────────────────────────────────────────────

def build_page_1(data, styles):
    """Page 1: Project Information & Roofing System"""
    elements = []

    # Proposal title block
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("COMMERCIAL ROOFING PROPOSAL", styles['ProposalTitle']))

    # Proposal meta info
    proposal_date = data.get("proposal_date", datetime.date.today().strftime("%B %d, %Y"))
    proposal_num = data.get("proposal_number", "P-001")
    valid_until = data.get("valid_until", "30 days from date of proposal")

    meta_data = [
        ["Proposal #:", proposal_num, "Date:", proposal_date],
        ["Valid Until:", valid_until, "", ""],
    ]
    meta_table = Table(meta_data, colWidths=[1.1 * inch, 2.1 * inch, 0.8 * inch, 2.5 * inch])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), BRAND_GRAY),
        ('TEXTCOLOR', (1, 0), (1, -1), BRAND_BLUE),
        ('TEXTCOLOR', (3, 0), (3, -1), BRAND_BLUE),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8))

    # Prepared For / Project Details
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_ACCENT, spaceAfter=6))

    # Two-column: Prepared For + Project Location
    prepared_for = data.get("prepared_for", {})
    left_col = []
    left_col.append(Paragraph("PREPARED FOR", styles['SubHeading']))
    left_col.append(Paragraph(prepared_for.get("company", "—"), styles['TableCellBold']))
    left_col.append(Paragraph(f"Attn: {prepared_for.get('contact_name', '—')}", styles['TableCell']))
    if prepared_for.get("contact_email"):
        left_col.append(Paragraph(prepared_for.get("contact_email", ""), styles['TableCell']))
    if prepared_for.get("contact_phone"):
        left_col.append(Paragraph(prepared_for.get("contact_phone", ""), styles['TableCell']))

    right_col = []
    right_col.append(Paragraph("PROJECT LOCATION", styles['SubHeading']))
    right_col.append(Paragraph(data.get("project_name", "—"), styles['TableCellBold']))
    right_col.append(Paragraph(data.get("project_address", "—"), styles['TableCell']))

    info_data = [[left_col, right_col]]
    info_table = Table(info_data, colWidths=[3.25 * inch, 3.25 * inch])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 8))

    # ── Roofing System Section ──
    elements.append(Paragraph("ROOFING SYSTEM", styles['SectionHeading']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=4))

    system_desc = data.get("roofing_system_description", "")
    if system_desc:
        elements.append(Paragraph(system_desc, styles['BodyText2']))
        elements.append(Spacer(1, 4))

    # Roofing line items table
    roofing_items = data.get("roofing_items", [])
    if roofing_items:
        headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
        rows = []
        for item in roofing_items:
            rows.append([
                item.get("item", ""),
                item.get("description", ""),
                item.get("qty", ""),
                item.get("unit", ""),
                item.get("unit_price", ""),
                item.get("total", ""),
            ])
        col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
        elements.append(make_styled_table(headers, rows, col_w))

    # Roofing metals
    roofing_metals = data.get("roofing_metals", [])
    if roofing_metals:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph("Roofing Related Metals", styles['SubHeading']))
        headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
        rows = []
        for item in roofing_metals:
            rows.append([
                item.get("item", ""),
                item.get("description", ""),
                item.get("qty", ""),
                item.get("unit", ""),
                item.get("unit_price", ""),
                item.get("total", ""),
            ])
        col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
        elements.append(make_styled_table(headers, rows, col_w))

    # Total for page 1
    roofing_total = data.get("roofing_total", "")
    if roofing_total:
        elements.append(Spacer(1, 4))
        elements.append(make_total_row_table("Roofing System Total:", roofing_total))

    # Exclusions / Notes
    exclusions = data.get("roofing_exclusions", [])
    if exclusions:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph("EXCLUSIONS", styles['SubHeading']))
        for exc in exclusions:
            elements.append(Paragraph(f"\u2022  {exc}", styles['SmallText']))

    notes = data.get("roofing_notes", [])
    if notes:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("NOTES", styles['SubHeading']))
        for note in notes:
            elements.append(Paragraph(f"\u2022  {note}", styles['SmallText']))

    return elements


def build_page_2(data, styles):
    """Page 2: Metal Roofing System (Standing Seam / R-Panels / Etc)"""
    elements = []
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("METAL ROOFING SYSTEM", styles['PageTitle']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=10))

    metal_type = data.get("metal_roof_type", "Standing Seam Metal Roof")
    elements.append(Paragraph(metal_type, styles['SectionHeading']))

    desc = data.get("metal_roof_description", "")
    if desc:
        elements.append(Paragraph(desc, styles['BodyText2']))
        elements.append(Spacer(1, 6))

    items = data.get("metal_roof_items", [])
    if items:
        headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
        rows = []
        for item in items:
            rows.append([
                item.get("item", ""),
                item.get("description", ""),
                item.get("qty", ""),
                item.get("unit", ""),
                item.get("unit_price", ""),
                item.get("total", ""),
            ])
        col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
        elements.append(make_styled_table(headers, rows, col_w))

    total = data.get("metal_roof_total", "")
    if total:
        elements.append(Spacer(1, 8))
        elements.append(make_total_row_table("Metal Roofing Total:", total))

    exclusions = data.get("metal_roof_exclusions", [])
    if exclusions:
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("EXCLUSIONS", styles['SubHeading']))
        for exc in exclusions:
            elements.append(Paragraph(f"\u2022  {exc}", styles['SmallText']))

    notes = data.get("metal_roof_notes", [])
    if notes:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("NOTES", styles['SubHeading']))
        for note in notes:
            elements.append(Paragraph(f"\u2022  {note}", styles['SmallText']))

    return elements


def build_page_3(data, styles):
    """Page 3: Wall Panels / Metal Siding / Column Wraps / Architectural Metals"""
    elements = []
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("WALL PANELS &amp; ARCHITECTURAL METALS", styles['PageTitle']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=10))

    # Sub-sections for wall panels, siding, column wraps, etc.
    sections = data.get("wall_panel_sections", [])
    for section in sections:
        elements.append(Paragraph(section.get("title", ""), styles['SectionHeading']))
        desc = section.get("description", "")
        if desc:
            elements.append(Paragraph(desc, styles['BodyText2']))

        items = section.get("items", [])
        if items:
            headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
            rows = []
            for item in items:
                rows.append([
                    item.get("item", ""),
                    item.get("description", ""),
                    item.get("qty", ""),
                    item.get("unit", ""),
                    item.get("unit_price", ""),
                    item.get("total", ""),
                ])
            col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
            elements.append(make_styled_table(headers, rows, col_w))
            elements.append(Spacer(1, 6))

    # If no sub-sections, allow flat items
    if not sections:
        items = data.get("wall_panel_items", [])
        if items:
            headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
            rows = [[
                i.get("item", ""), i.get("description", ""),
                i.get("qty", ""), i.get("unit", ""),
                i.get("unit_price", ""), i.get("total", ""),
            ] for i in items]
            col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
            elements.append(make_styled_table(headers, rows, col_w))

    total = data.get("wall_panel_total", "")
    if total:
        elements.append(Spacer(1, 8))
        elements.append(make_total_row_table("Wall Panels / Metals Total:", total))

    exclusions = data.get("wall_panel_exclusions", [])
    if exclusions:
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("EXCLUSIONS", styles['SubHeading']))
        for exc in exclusions:
            elements.append(Paragraph(f"\u2022  {exc}", styles['SmallText']))

    notes = data.get("wall_panel_notes", [])
    if notes:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("NOTES", styles['SubHeading']))
        for note in notes:
            elements.append(Paragraph(f"\u2022  {note}", styles['SmallText']))

    return elements


def build_page_4(data, styles):
    """Page 4: Awnings / Canopies"""
    elements = []
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("AWNINGS &amp; CANOPIES", styles['PageTitle']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=10))

    desc = data.get("awning_description", "")
    if desc:
        elements.append(Paragraph(desc, styles['BodyText2']))
        elements.append(Spacer(1, 6))

    items = data.get("awning_items", [])
    if items:
        headers = ["Item", "Description", "Qty", "Unit", "Unit Price", "Total"]
        rows = [[
            i.get("item", ""), i.get("description", ""),
            i.get("qty", ""), i.get("unit", ""),
            i.get("unit_price", ""), i.get("total", ""),
        ] for i in items]
        col_w = [0.4 * inch, 2.1 * inch, 0.75 * inch, 0.5 * inch, 0.9 * inch, 0.95 * inch]
        elements.append(make_styled_table(headers, rows, col_w))

    total = data.get("awning_total", "")
    if total:
        elements.append(Spacer(1, 8))
        elements.append(make_total_row_table("Awnings / Canopies Total:", total))

    exclusions = data.get("awning_exclusions", [])
    if exclusions:
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("EXCLUSIONS", styles['SubHeading']))
        for exc in exclusions:
            elements.append(Paragraph(f"\u2022  {exc}", styles['SmallText']))

    notes = data.get("awning_notes", [])
    if notes:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("NOTES", styles['SubHeading']))
        for note in notes:
            elements.append(Paragraph(f"\u2022  {note}", styles['SmallText']))

    return elements


def build_page_5(data, styles):
    """Page 5: About Roof Experts"""
    elements = []
    elements.append(Spacer(1, 14))
    elements.append(Paragraph("ABOUT ROOF EXPERTS", styles['PageTitle']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=8))

    company = data.get("company_info", {})

    about_text = company.get("about", (
        "Roof Experts is a full-service commercial roofing company providing quality "
        "roofing solutions to businesses across the Houston metropolitan area and beyond. "
        "With decades of combined experience, our team specializes in new construction, "
        "re-roofing, roof repairs, and preventive maintenance programs for commercial and "
        "industrial buildings."
    ))
    elements.append(Paragraph(about_text, styles['BodyText2']))
    elements.append(Spacer(1, 8))

    # Services
    elements.append(Paragraph("OUR SERVICES", styles['SectionHeading']))
    services = company.get("services", [
        "New Construction Roofing (TPO, EPDM, PVC, Modified Bitumen)",
        "Standing Seam &amp; Metal Roofing Systems",
        "Wall Panels, Metal Siding &amp; Architectural Metals",
        "Awnings &amp; Canopy Systems",
        "Roof Repairs &amp; Emergency Leak Response",
        "Preventive Maintenance Programs",
        "Roof Inspections &amp; Condition Assessments",
    ])
    for svc in services:
        elements.append(Paragraph(f"\u2022  {svc}", styles['SmallText']))
    elements.append(Spacer(1, 8))

    # Certifications / credentials
    elements.append(Paragraph("CERTIFICATIONS &amp; CREDENTIALS", styles['SectionHeading']))
    certs = company.get("certifications", [
        "Licensed &amp; Insured General Contractor",
        "Manufacturer Certified Installer",
        "OSHA Safety Compliant",
    ])
    for cert in certs:
        elements.append(Paragraph(f"\u2022  {cert}", styles['SmallText']))
    elements.append(Spacer(1, 8))

    # Why choose us
    elements.append(Paragraph("WHY CHOOSE ROOF EXPERTS", styles['SectionHeading']))
    reasons = company.get("why_choose_us", [
        "Competitive pricing with transparent, detailed proposals",
        "Experienced crews dedicated to commercial roofing",
        "Manufacturer-backed warranties on materials and workmanship",
        "On-time project completion with minimal disruption to your business",
        "Dedicated project manager for every job",
    ])
    for r in reasons:
        elements.append(Paragraph(f"\u2022  {r}", styles['SmallText']))
    elements.append(Spacer(1, 14))

    # Contact block
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_ACCENT, spaceAfter=8))
    elements.append(Paragraph("CONTACT US", styles['SectionHeading']))

    contact_info = [
        f"<b>{company.get('name', 'Roof Experts')}</b>",
        company.get("address", ""),
        f"Phone: {company.get('phone', '')}",
        f"Email: {company.get('email', '')}",
        company.get("website", ""),
    ]
    for line in contact_info:
        if line:
            elements.append(Paragraph(line, styles['BodyText2']))

    return elements


def build_grand_total_section(data, styles):
    """Grand total summary across all included pages."""
    elements = []
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=BRAND_BLUE, spaceAfter=4))
    elements.append(Paragraph("PROPOSAL SUMMARY", styles['SectionHeading']))

    totals = []
    if data.get("roofing_total"):
        totals.append(["Roofing System", data["roofing_total"]])
    if data.get("include_metal_roof") and data.get("metal_roof_total"):
        totals.append(["Metal Roofing", data["metal_roof_total"]])
    if data.get("include_wall_panels") and data.get("wall_panel_total"):
        totals.append(["Wall Panels / Metals", data["wall_panel_total"]])
    if data.get("include_awnings") and data.get("awning_total"):
        totals.append(["Awnings / Canopies", data["awning_total"]])

    if totals:
        t = Table(totals, colWidths=[4.5 * inch, 2.0 * inch])
        t.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (-1, -1), BRAND_GRAY),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)

    grand_total = data.get("grand_total", "")
    if grand_total:
        elements.append(make_total_row_table("GRAND TOTAL:", grand_total))

    return elements


def build_terms_section(data, styles):
    """Terms & Conditions + Signature block."""
    elements = []
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("TERMS &amp; CONDITIONS", styles['SectionHeading']))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=6))

    terms = data.get("terms", [
        "Payment terms: 50% deposit upon acceptance, balance due upon completion.",
        "Work to commence within 2-4 weeks of signed acceptance, weather permitting.",
        "All work performed in accordance with local building codes and manufacturer specifications.",
        "Warranty: Manufacturer warranty on materials; 2-year workmanship warranty.",
        "Any changes to scope of work will be documented via written change order.",
        "This proposal is valid for 30 days from the date above.",
    ])
    for i, term in enumerate(terms, 1):
        elements.append(Paragraph(f"{i}. {term}", styles['SmallText']))
        elements.append(Spacer(1, 2))

    # Signature block — keep together so it doesn't split across pages
    sig_elements = []
    sig_elements.append(Spacer(1, 12))
    sig_data = [
        ["ACCEPTED BY:", "", "ROOF EXPERTS:"],
        ["", "", ""],
        ["_" * 40, "", "_" * 40],
        ["Signature", "", "Signature"],
        ["", "", ""],
        ["_" * 40, "", "_" * 40],
        ["Printed Name", "", "Printed Name"],
        ["", "", ""],
        ["_" * 40, "", "_" * 40],
        ["Date", "", "Date"],
    ]
    sig_table = Table(sig_data, colWidths=[2.8 * inch, 0.9 * inch, 2.8 * inch])
    sig_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), BRAND_GRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    sig_elements.append(sig_table)
    elements.append(KeepTogether(sig_elements))

    return elements


# ── Main Generator ────────────────────────────────────────────

def generate_proposal_pdf(data: dict) -> bytes:
    """
    Generate a complete proposal PDF and return as bytes.

    data keys:
      Required:
        - project_name (str)
        - project_address (str)
        - proposal_number (str)
        - proposal_date (str)
        - company_info (dict): name, tagline, phone, email, website, address, license
        - prepared_for (dict): company, contact_name, contact_email, contact_phone
        - roofing_items (list of dicts): item, description, qty, unit, unit_price, total
        - roofing_total (str)

      Optional toggles:
        - include_metal_roof (bool, default False)
        - include_wall_panels (bool, default False)
        - include_awnings (bool, default False)

      Optional per-page data (see build_page_2/3/4 for keys)

      Optional:
        - grand_total (str)
        - terms (list of str)
        - valid_until (str)
        - roofing_system_description (str)
        - roofing_metals (list of dicts)
        - roofing_exclusions (list of str)
        - roofing_notes (list of str)
    """
    buffer = io.BytesIO()
    styles = get_custom_styles()

    company_info = data.get("company_info", {})
    template = ProposalTemplate(company_info)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=80,
        bottomMargin=60,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"Proposal - {data.get('project_name', 'Project')}",
        author=company_info.get("name", "Roof Experts"),
    )

    story = []

    # ── Page 1: Project Info + Roofing System (always) ──
    story.extend(build_page_1(data, styles))

    # ── Page 2: Metal Roofing (optional) ──
    if data.get("include_metal_roof"):
        story.append(PageBreak())
        story.extend(build_page_2(data, styles))

    # ── Page 3: Wall Panels / Architectural Metals (optional) ──
    if data.get("include_wall_panels"):
        story.append(PageBreak())
        story.extend(build_page_3(data, styles))

    # ── Page 4: Awnings / Canopies (optional) ──
    if data.get("include_awnings"):
        story.append(PageBreak())
        story.extend(build_page_4(data, styles))

    # ── Grand Total Summary (if multi-page) ──
    has_extras = any([
        data.get("include_metal_roof"),
        data.get("include_wall_panels"),
        data.get("include_awnings"),
    ])
    if has_extras and data.get("grand_total"):
        story.extend(build_grand_total_section(data, styles))

    # ── Terms & Signature ──
    story.extend(build_terms_section(data, styles))

    # ── Page 5: About (always, new page) ──
    story.append(PageBreak())
    story.extend(build_page_5(data, styles))

    # Build the PDF
    doc.build(story, onFirstPage=template.header_footer, onLaterPages=template.header_footer)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
