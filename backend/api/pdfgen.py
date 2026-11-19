"""Tiny dependency-free PDF writer (Courier text pages) for account statements."""


def _esc(t):
    t = str(t).replace('₹', 'Rs.').encode('latin-1', 'replace').decode('latin-1')
    return t.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def make_pdf(header, rows, per_page=44):
    """header: list of text lines (first page). rows: list of text lines (table). Returns bytes."""
    pages, first = [], True
    i = 0
    while first or i < len(rows):
        top = list(header) if first else []
        take = per_page - len(top)
        pages.append((top, rows[i:i + take]))
        i += max(take, 0)
        first = False
    objs = []
    objs.append('<< /Type /Catalog /Pages 2 0 R >>')
    kids = ' '.join(f'{4 + 2 * n} 0 R' for n in range(len(pages)))
    objs.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>')
    objs.append('<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>')
    for n, (top, body) in enumerate(pages):
        y, cmds = 800, ['BT', '/F1 9 Tf', '11 TL']
        cmds.append(f'40 {y} Td')
        for line in top + body:
            cmds.append(f'({_esc(line)}) Tj T*')
        cmds.append('ET')
        cmds.append(f'BT /F1 8 Tf 40 24 Td (Page {n + 1} of {len(pages)} - computer generated statement) Tj ET')
        stream = '\n'.join(cmds)
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * n} 0 R >>')
        objs.append(f'<< /Length {len(stream.encode("latin-1", "replace"))} >>\nstream\n{stream}\nendstream')
    out = bytearray(b'%PDF-1.4\n')
    offs = []
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f'{k} 0 obj\n{o}\nendobj\n'.encode('latin-1', 'replace')
    x = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    for o in offs:
        out += f'{o:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF'.encode()
    return bytes(out)
