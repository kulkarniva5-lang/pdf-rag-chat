"""Generate samples/solar-handbook.pdf, a small fictional document to try the demo with.

Dependency-free: writes a minimal multi-page PDF by hand.
Usage: python scripts/make_sample_pdf.py
"""

from pathlib import Path

PAGES = [
    [
        "Northwind Solar - Employee Handbook (2026 edition)",
        "",
        "1. About Northwind Solar",
        "Northwind Solar was founded in 2014 in Boulder, Colorado. The company designs",
        "and installs rooftop solar systems for homes and small businesses. As of 2026",
        "Northwind employs 240 people across four offices: Boulder, Denver, Austin and",
        "Phoenix. Our mission is to make clean energy the cheapest option for every roof.",
        "",
        "2. Working hours",
        "Core hours are 10:00 to 15:00 local time. Outside core hours, employees may",
        "schedule their work flexibly. Installation crews work fixed shifts from 07:00",
        "to 15:30 between April and October, and 08:00 to 16:00 from November to March.",
    ],
    [
        "3. Paid time off",
        "Full-time employees receive 22 days of paid vacation per year, plus 10 public",
        "holidays. Vacation accrues monthly. Up to 5 unused days can be carried over",
        "into the next calendar year; any remaining days expire on March 31.",
        "Employees also receive 8 sick days per year, which do not carry over.",
        "",
        "4. Parental leave",
        "Primary caregivers receive 16 weeks of fully paid parental leave. Secondary",
        "caregivers receive 8 weeks. Leave may be taken within 12 months of the birth",
        "or adoption and can be split into at most two blocks.",
    ],
    [
        "5. Safety on installation sites",
        "Every crew member must complete the 3-day Roof Safety certification before",
        "their first install, and renew it every 24 months. Harnesses must be worn on",
        "any roof with a pitch above 4:12. Work stops when sustained wind exceeds",
        "25 mph or when lightning is detected within 10 miles.",
        "",
        "6. Learning budget",
        "Each employee has an annual learning budget of 1,500 USD for courses, books",
        "and conferences. NABCEP certification fees are covered separately and in full.",
    ],
]


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog = add(b"")  # placeholder, filled below
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids = []
    for lines in pages:
        ops = ["BT", "/F1 11 Tf", "14 TL", "60 760 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_obj, font, content)
            )
        )

    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(out)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "samples" / "solar-handbook.pdf"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(build_pdf(PAGES))
    print(f"Wrote {target}")
