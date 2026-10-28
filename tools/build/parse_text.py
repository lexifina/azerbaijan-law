"""Parse one e-qanun Word-exported HTML text into blocks, articles and endnotes.

parse(raw_bytes) -> {
  'title':    [lines before the first article],
  'title_notes': [note numbers referenced in the title part, in order],
  'units':    [{'id': '98-1', 'lines': [...], 'notes': [n, ...]}],   # one per "Maddə N." article
  'notes':    {n: [paragraph lines]},                               # e-qanun's endnotes, by their number
}

Rules:
- Blocks are <p>, <h1-6>, <li> and table rows (cells joined with " | "; a nested table stays inside its cell).
- e-qanun's endnote references (<a href="#_ednN">[N]</a>) are removed from the text and remembered per block; the
  file writer renumbers them per file, so a note added elsewhere in the act does not touch every later article.
- <sup>1</sup> after an article number (Maddə 98<sup>1</sup>) is written as a Unicode superscript in the text and as
  "98-1" in the file name, the form the acts themselves use when they cite it ("98-1-ci maddə").
- An article starts at a block that begins "Maddə N." (N may be 13-1, 13.1 or 98 followed by a superscript), unless
  the block is inside quoted text: it begins with a quote mark, or a quote opened earlier in the article (“ or «) is
  not yet closed. That keeps articles quoted by an amending act inside the amending act's own article.
- Soft hyphens, zero-width characters and non-breaking spaces are normalised; whitespace is collapsed.
"""
import html
import re
from html.parser import HTMLParser

SUP = str.maketrans('0123456789', '\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079')
SUP_BACK = {v: k for k, v in zip('0123456789', '\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079')}
JUNK = re.compile('[\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]')
SPACE = re.compile(r'[\s\u00a0\u2002-\u200a\u202f\u205f\u3000]+')
NOTE_HREF = re.compile(r'^#_(edn|ftn)(\d+)$')   # only links within the page: e-qanun also links to other acts' notes
NOTE_DIV = re.compile(r'^(edn|ftn)(\d+)$')
BLOCKS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'br'}


def decode(raw: bytes) -> str:
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):      # some texts are served as UTF-16 with a byte-order mark
        return raw.decode('utf-16')
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000])
    enc = (m.group(1).decode('ascii').lower() if m else 'utf-8')
    if enc in ('windows-1251', 'cp1251'):
        enc = 'cp1251'
    try:
        return raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return raw.decode('utf-8', errors='replace')


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []        # (where, text, [note refs]); where = 'main' or ('note', n)
        self.buf = []
        self.refs = []
        self.where = 'main'
        self.stack = []         # open tags with flags
        self.skip = 0           # inside a note-reference anchor, script, style, hidden
        self.sup = 0
        self.table = 0          # table depth
        self.cells = []         # cells of the current outermost row
        self.div_note = []      # stack of div kinds

    def flush(self):
        t = clean(''.join(self.buf))
        if self.table:
            self.buf = [t + ' '] if t else []
            return
        if t:
            self.blocks.append((self.where, t, self.refs))
        self.buf, self.refs = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        style = (a.get('style') or '').replace(' ', '').lower()
        if tag in ('script', 'style', 'title', 'head') or 'display:none' in style:
            self.stack.append((tag, 'skip'))
            self.skip += 1
            return
        if tag == 'a':
            m = NOTE_HREF.search(a.get('href') or '')
            if m:
                if self.where == 'main':
                    n = int(m.group(2)) if m.group(1) == 'edn' else 100000 + int(m.group(2))
                    self.refs.append(n)
                    self.buf.append('\x01' + str(n) + '\x02')
                self.stack.append((tag, 'skip'))
                self.skip += 1
                return
        if tag == 'div':
            m = NOTE_DIV.match(a.get('id') or '')
            if m and ('mso-element:endnote' in style or 'mso-element:footnote' in style):
                self.flush()
                self.where = ('note', int(m.group(2)) if m.group(1) == 'edn' else 100000 + int(m.group(2)))
                self.stack.append((tag, 'note'))
                return
            if 'mso-element:endnote-list' in style or 'mso-element:footnote-list' in style or \
                    'separator' in style:
                self.stack.append((tag, 'plain'))
                return
        if tag == 'sup':
            self.sup += 1
            self.stack.append((tag, 'sup'))
            return
        if tag == 'table':
            if not self.table:
                self.flush()
            self.table += 1
        elif tag == 'tr' and self.table == 1:
            self.cells = []
            self.buf = []
        elif tag in ('td', 'th') and self.table == 1:
            self.buf = []
        elif tag == 'tr' and self.table > 1:
            self.buf.append(' / ')
        elif tag in ('td', 'th') and self.table > 1:
            self.buf.append(' ')
        elif tag in BLOCKS and not self.table:
            if tag == 'br':
                self.buf.append(' ')
                return
            self.flush()
        elif tag in ('p', 'br', 'div', 'li') and self.table:
            self.buf.append(' ')
            if tag == 'br':
                return
        if tag in ('br', 'img', 'meta', 'link', 'input', 'hr'):
            return
        self.stack.append((tag, ''))

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.buf.append(' ')

    def handle_endtag(self, tag):
        # Pop to the matching tag (Word HTML is mostly well formed).
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            return
        for t, flag in reversed(self.stack[idx:]):
            self._close(t, flag)
        del self.stack[idx:]

    def _close(self, tag, flag):
        if flag == 'skip':
            self.skip -= 1
            return
        if flag == 'sup':
            self.sup -= 1
            return
        if flag == 'note':
            self.flush()
            self.where = 'main'
            return
        if tag == 'table':
            self.table -= 1
            return
        if self.table == 1 and tag in ('td', 'th'):
            self.cells.append(clean(''.join(self.buf)))
            self.buf = []
            return
        if self.table == 1 and tag == 'tr':
            cells = self.cells
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                self.blocks.append((self.where, ' | '.join(cells), self.refs))
            self.cells, self.buf, self.refs = [], [], []
            return
        if tag in BLOCKS and not self.table:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.sup:
            d = data.strip()
            if d.isdigit():
                data = data.translate(SUP)    # keep any space around the digits
        self.buf.append(data)


def clean(s: str) -> str:
    s = JUNK.sub('', s)
    return SPACE.sub(' ', s).strip()


ART = re.compile(r'^Madd[\u0259e]\s+(\d+(?:[-.]\d+)*)([\u2070\u00b9\u00b2\u00b3\u2074-\u2079]*)(?:-\d+)?\s*\.?(?=\s|$)')
QUOTE_START = re.compile(r'^[\u201c"\u00ab\u201e\'\u2018]')


def art_id(m: re.Match) -> str:
    base, sup = m.group(1), m.group(2)
    if sup:
        base += '-' + ''.join(SUP_BACK[c] for c in sup)
    return base


def parse(raw: bytes) -> dict:
    text = decode(raw)
    i = text.lower().find('<body')
    p = _P()
    p.feed(text[i if i >= 0 else 0:])
    p.flush()
    notes: dict[int, list[str]] = {}
    main = []
    for where, t, refs in p.blocks:
        if where == 'main':
            main.append((t, refs))
        else:
            n = where[1]
            t = re.sub(r'^\[\d+\]\s*', '', t) if n not in notes else t
            if t:
                notes.setdefault(n, []).append(t)
    title, title_notes, units = [], [], []
    seen = set()
    depth = 0
    cur = None
    for t, refs in main:
        m = ART.match(t)
        ok = bool(m) and not QUOTE_START.match(t) and art_id(m) not in seen
        if ok and depth > 0:
            # Inside an unclosed quote: only the next article in sequence counts (publishers leave quotes open).
            major = int(re.match(r'\d+', art_id(m)).group(0))
            last = int(re.match(r'\d+', cur['id']).group(0)) if cur else 0
            ok = major in (last, last + 1)
        if ok:
            cur = {'id': art_id(m), 'lines': [], 'notes': []}
            seen.add(cur['id'])
            units.append(cur)
            depth = 0
        target = cur['lines'] if cur else title
        target.append(t)
        (cur['notes'] if cur else title_notes).extend(refs)
        depth += t.count('\u201c') + t.count('\u00ab') - t.count('\u201d') - t.count('\u00bb')
    return {'title': title, 'title_notes': title_notes, 'units': units, 'notes': notes}


# The official-publication reference in a note, e.g. "(“Azərbaycan” qəzeti, 24 iyun 2021-ci il, № 130, Azərbaycan
# Respublikasının Qanunvericilik Toplusu, 2021-ci il, № 6, maddə 559)". e-qanun fills it in over the months after a
# change, which would otherwise show as a change to every article the act touched. It is removed from the notes; the
# act's own publication dates are in the commit trailers.
PUBREF = re.compile(r'\s*\((?=(?:[^()]|\([^()]*\))*?(?:qəzet|Toplusu|internet sayt|Bülleten|Xəbərlər|jurnal|Məcmuə))'
                    r'(?:[^()]|\([^()]*\))*\)')
MARK = re.compile('\x01(\\d+)\x02')


def unit_text(lines: list[str], notes: dict[int, list[str]]) -> str:
    """File text: the lines, with e-qanun's note references renumbered [^1], [^2] ... per file, then those notes."""
    order = []
    for ln in lines:
        for m in MARK.finditer(ln):
            r = int(m.group(1))
            if r not in order:
                order.append(r)
    num = {r: k for k, r in enumerate(order, 1)}
    out = [MARK.sub(lambda m: f'[^{num[int(m.group(1))]}]', ln) for ln in lines]
    if order:
        out.append('')
        for k, r in enumerate(order, 1):
            body = [PUBREF.sub('', b) for b in notes.get(r) or ['(note text missing in the source)']]
            out.append(f'[^{k}]: {body[0]}')
            out += ['    ' + b for b in body[1:]]
    return '\n'.join(out) + '\n'
