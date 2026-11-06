"""Small synthetic ML text with known pages; no copyrighted textbook content."""

from io import BytesIO
from textwrap import wrap

from reportlab.pdfgen.canvas import Canvas

PAGES = [
    "Chapter 1: Overfitting. Overfitting occurs when a model memorizes training noise "
    "and performs poorly on unseen examples. High variance is an indicator of overfitting.",
    "Chapter 2: Preventing overfitting. Techniques for reducing overfitting include "
    "cross-validation, regularization and early stopping. Cross-validation estimates "
    "generalization using held-out folds.",
    "Chapter 5: Regularization and early stopping. Regularization reduces overfitting "
    "by penalizing large weights. For example, L2 regularization adds a squared-weight "
    "penalty to the training loss. Early stopping ends training when validation loss rises.",
    "Chapter 6: Random forests. Random forests combine trees and reduce variance. "
    "Disadvantages of random forests include memory cost and limited interpretability.",
]


def textbook_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    for paragraph in PAGES:
        text = canvas.beginText(72, 740)
        for line in wrap(paragraph, 88):
            text.textLine(line)
        canvas.drawText(text)
        canvas.showPage()
    canvas.save()
    return output.getvalue()
