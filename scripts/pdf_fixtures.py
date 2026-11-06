"""Synthetic fixtures only; never evidence of real-world extraction accuracy."""

import io
from pathlib import Path

import pymupdf
import reportlab
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle


def synthetic_pdf(kind: str = "text", pages: int = 2) -> bytes:
    if kind in {"scan", "mixed", "figure"}:
        image = Image.new("RGB", (1400, 900), "white")
        draw = ImageDraw.Draw(image)
        font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
        font = ImageFont.truetype(str(font_path), 48)
        draw.text((80, 130), "ALPHA REVENUE IS 42 MILLION", fill="black", font=font)
        draw.text((80, 230), "LEAVE POLICY IS 25 DAYS", fill="black", font=font)
        if kind == "figure":
            draw.rectangle((120, 420, 350, 750), fill="blue")
            draw.rectangle((500, 570, 730, 750), fill="green")
            draw.text((120, 790), "A = 42      B = 25", fill="black", font=font)
        data = io.BytesIO()
        image.save(data, format="PNG")
        with pymupdf.open() as document:
            if kind == "mixed":
                page = document.new_page()
                page.insert_text(
                    (72, 72), "Alpha revenue is 42 million. This is the digital text page."
                )
            page = document.new_page(width=700, height=500)
            if kind == "figure":
                page.insert_text(
                    (30, 30), "Figure 1. Revenue comparison for Alpha model A and model B."
                )
            page.insert_image(pymupdf.Rect(20, 50, 680, 480), stream=data.getvalue())
            return document.tobytes()
    output = io.BytesIO()
    canvas = Canvas(output)
    if kind == "table":
        canvas.drawString(72, 760, "Table 3. Model accuracy and latency comparison")
        table = Table(
            [
                ["Model comparison", "", "", ""],
                ["Approach", "Accuracy (%)", "Latency (ms)", "Dataset"],
                ["Model A", "88", "20", "Test"],
                ["Model B", "94", "15", "Test"],
            ],
            colWidths=[120, 120, 120, 100],
            rowHeights=35,
        )
        table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
                ]
            )
        )
        table.wrapOn(canvas, 500, 200)
        table.drawOn(canvas, 72, 580)
        canvas.save()
        return output.getvalue()
    for number in range(pages):
        canvas.drawString(72, 810, "SYNTHETIC RESEARCH BOOK")
        canvas.drawString(72, 770, f"SECTION {number + 1}")
        if kind == "columns":
            for line in range(10):
                canvas.drawString(
                    60, 700 - line * 20, f"Left column paragraph {line} alpha revenue."
                )
                canvas.drawString(
                    325, 700 - line * 20, f"Right column paragraph {line} beta policy."
                )
        else:
            canvas.drawString(
                72, 720, f"Alpha revenue is 42 million on synthetic page {number + 1}."
            )
            canvas.drawString(72, 690, "The leave policy provides 25 days for model B research.")
        canvas.drawString(72, 30, f"Page {number + 1}")
        canvas.showPage()
    canvas.save()
    return output.getvalue()
