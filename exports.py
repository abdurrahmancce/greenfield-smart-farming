"""CSV and PDF downloads of a user's own farm records."""
import csv
import io
from xml.sax.saxutils import escape

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    """Spreadsheet formula injection guard: text that Excel/Sheets would run as a formula
    (starts with = + - @) is prefixed with an apostrophe. Real numbers are left alone."""
    if isinstance(v, (int, float)):
        return v
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_START) else s


def make_csv(headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([safe_cell(c) for c in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")        # BOM: Excel opens Bangla text correctly


def _latin(s):
    """The built-in PDF fonts only know Latin letters; anything else becomes '?' instead of a black box."""
    return escape(("" if s is None else str(s)).encode("latin-1", "replace").decode("latin-1"))


def make_pdf(user_name, today, farms, expenses, irrigations, totals):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    cell = st["BodyText"].clone("cell", fontSize=8, leading=10)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm,
                            title="GreenField farm report", author="GreenField Smart Farming")
    story = [Paragraph("GreenField - Farm Report", st["Title"]),
             Paragraph(_latin("Prepared for %s on %s" % (user_name, today)), st["Normal"]), Spacer(1, 6 * mm)]

    def table(title, headers, rows, widths):
        story.append(Paragraph(title, st["Heading3"]))
        if not rows:
            story.append(Paragraph("No records.", st["Italic"])); story.append(Spacer(1, 4 * mm)); return
        data = [[Paragraph("<b>%s</b>" % h, cell) for h in headers]] + [[Paragraph(_latin(c), cell) for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C8E6C9")),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.extend([t, Spacer(1, 5 * mm)])

    income, expense = totals
    table("Money summary (all records)", ["Income", "Expenses", "Profit / loss"],
          [["%.2f" % income, "%.2f" % expense, "%.2f" % (income - expense)]], [50, 50, 50])
    table("Farms", ["Farm", "Crop", "Location", "Area", "Planted", "Status"],
          [[f["farm_name"], f["crop_type"], f["location"], f["area"], f["planting_date"], f["status"]] for f in farms],
          [38, 28, 38, 18, 26, 26])
    table("Income and expenses (latest 200)", ["Date", "Farm", "Type", "Category", "Amount", "Note"],
          [[e["date"], e["farm_name"], e["type"], e["category"], "%.2f" % e["amount"], e["description"]] for e in expenses],
          [22, 30, 18, 26, 20, 66])
    table("Irrigation (latest 200)", ["Date", "Farm", "Method", "Litres", "Minutes", "Note"],
          [[i["date"], i["farm_name"], i["method"], i["water_liters"], i["duration_min"], i["notes"]] for i in irrigations],
          [22, 34, 26, 20, 20, 60])
    doc.build(story)
    return buf.getvalue()
