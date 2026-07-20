"""Render a realistic, internally-consistent electrical Schedule of Loads +
board summary to fixtures/electrical-schedule.pdf (clean vector text).
Used as the permanent fixture for the electrical pack. Deterministic."""
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from collections import defaultdict


def build(path):
    W, H = landscape(A3)
    c = canvas.Canvas(path, pagesize=(W, H))
    c.setFont('Helvetica-Bold', 14)
    c.drawString(20 * mm, H - 18 * mm, 'ELECTRICAL SCHEDULE OF LOADS')
    c.setFont('Helvetica', 9)
    c.drawString(20 * mm, H - 24 * mm, 'Supply: 400V 3-phase 4-wire 50Hz')

    cx = {'Board': 20, 'Circuit': 42, 'Description': 62, 'Connected_VA': 112,
          'Demand_Factor': 140, 'Demand_VA': 162, 'Poles': 192, 'Breaker_AT': 210,
          'Cable_mm2': 234, 'Phase': 262}
    hdr = list(cx.keys())
    circuits = [
        ('DB-1', '1', 'Lighting', 1200, 1.0, '1P', 16, '2.5', 'A'),
        ('DB-1', '2', 'Power', 2000, 0.85, '1P', 20, '4.0', 'B'),
        ('DB-1', '3', 'HVAC', 4000, 0.78, '3P', 25, '6.0', 'C'),
        ('DB-1', '4', 'Spare', 0, 0.0, '3P', 20, '2.5', 'A'),
        ('DB-2', '1', 'Lighting', 1400, 1.0, '1P', 16, '2.5', 'A'),
        ('DB-2', '2', 'Power', 2200, 0.85, '1P', 20, '4.0', 'B'),
        ('DB-2', '3', 'HVAC', 4300, 0.78, '3P', 25, '6.0', 'C'),
        ('DB-2', '4', 'Small Power', 1800, 0.8, '1P', 32, '6.0', 'A'),
        ('MSB', '1', 'Lighting', 1600, 1.0, '1P', 16, '2.5', 'A'),
        ('MSB', '2', 'Power', 2400, 0.85, '1P', 20, '4.0', 'B'),
        ('MSB', '3', 'HVAC', 4600, 0.78, '3P', 25, '6.0', 'C'),
        ('MSB', '4', 'Pumps', 900, 1.0, '3P', 40, '16', 'B'),
    ]
    rows = []
    for b, ck, desc, conn, df, poles, brk, cab, ph in circuits:
        rows.append((b, ck, desc, str(conn), f'{df:.2f}', f'{round(conn * df, 2)}',
                     poles, str(brk), cab, ph))

    y = H - 36 * mm
    c.setFont('Helvetica-Bold', 8)
    for h in hdr:
        c.drawString(cx[h] * mm, y, h)
    c.setFont('Helvetica', 8)
    y -= 6 * mm
    for r in rows:
        for h, val in zip(hdr, r):
            c.drawString(cx[h] * mm, y, val)
        y -= 5 * mm

    conn_sum, dem_sum = defaultdict(float), defaultdict(float)
    for r in rows:
        conn_sum[r[0]] += float(r[3])
        dem_sum[r[0]] += float(r[5])
    bx = {'Board': 20, 'Connected_VA': 45, 'Demand_VA': 78,
          'Main_Breaker_AT': 112, 'Feeder_mm2': 145}
    y -= 10 * mm
    c.setFont('Helvetica-Bold', 10)
    c.drawString(20 * mm, y, 'BOARD SUMMARY')
    y -= 6 * mm
    c.setFont('Helvetica-Bold', 8)
    for h in bx:
        c.drawString(bx[h] * mm, y, h)
    c.setFont('Helvetica', 8)
    y -= 5 * mm
    mains = {'DB-1': 250, 'DB-2': 250, 'MSB': 400}
    feeders = {'DB-1': '120', 'DB-2': '120', 'MSB': '185'}
    for b in ['DB-1', 'DB-2', 'MSB']:
        vals = [b, str(int(conn_sum[b])), f'{dem_sum[b]:.2f}', str(mains[b]), feeders[b]]
        for h, val in zip(bx, vals):
            c.drawString(bx[h] * mm, y, val)
        y -= 5 * mm
    c.save()
    return path


if __name__ == '__main__':
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(build(os.path.join(root, 'fixtures', 'electrical-schedule.pdf')))
