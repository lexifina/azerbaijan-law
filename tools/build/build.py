"""Build the Azerbaijan law repository from the e-qanun.az cache.

    python build.py ~/Documents/azerbaijan-law --today YYYY-MM-DD [--workers 8] [--only ID,ID] [--no-write]

What e-qanun gives for each act (fetch.py): the current text (frameworks/f_<id>.html), and for many acts a list of
dated editions (versions/.../v_<id>_<n>.html, the original sometimes as c_<n>.html or v_<id>_1.html). Each text
carries e-qanun's endnotes, one per change, naming the amending act: "21 iyun 2025-ci il tarixli 216-VIIQD nömrəli
Azərbaycan Respublikasının Qanunu (...) ilə 1323-cü maddə ləğv edilmişdir."

How the history is made:
1. Every edition is parsed (parse_text.py) into one file per article (madde-<N>.md) plus title.md, each with the
   notes it references, renumbered per file.
2. Between two editions, each changed file is credited to the act its notes newly cite (`Evidence: e-qanun note`).
   A changed file whose notes cite no new act goes to the one act newly cited anywhere in that edition, if there is
   exactly one (`Evidence: e-qanun edition`); otherwise it is a labelled publisher commit (`Kind: unexplained`). A
   file that newly cites several acts is a labelled publisher commit naming each (`Kind: several`, `Candidate:`).
3. The first text of an act is its original when e-qanun has the act as adopted (c_ or v_<id>_1). Otherwise e-qanun
   only has a later consolidation: its files that carry no amendment note are the original text (`Kind: original`),
   and files that do carry notes appear only from the in-force date of the latest act they cite, as a labelled
   publisher commit (`Kind: baseline`, `Candidate:` per act), because their earlier wording is not in the source.
4. Dates: each act's in-force date from e-qanun's requisites ("effectDate"); where e-qanun gives none, its first
   official publication date (In-force-basis says which). Noon Baku time (+04:00, no DST since 2016; Azerbaijan kept
   +04:00 standard time throughout, with summer time +05:00 from 1997 to 2015 which we do not model: noon is used
   only to keep the day). Changes are applied in in-force order; a change that an earlier edition printed before an
   earlier-in-force change is re-applied by a three-way line merge, or held back (`Held-back:`).
5. One commit per act per in-force date, authored by that act. Commits dated after --today go on `future`, never
   merged. A repealed act's files are deleted on the repealing act's in-force date.
"""
import argparse
import bisect
import difflib
import gzip
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import parse_text  # noqa: E402

CACHE = HERE / '.cache'
PARSED = CACHE / 'parsed'
PARSER_VERSION = '6'
COMMITTER = 'Lexifina <azerbaijan-law@lexifina.com>'
PUBLISHER = ('e-qanun.az (Ministry of Justice of Azerbaijan)', 'publisher@e-qanun.invalid')
SITE = 'https://e-qanun.az/'
INFORCE = 'Qüvvədədir'

MONTHS = {'yanvar': 1, 'fevral': 2, 'mart': 3, 'aprel': 4, 'may': 5, 'iyun': 6, 'iyul': 7, 'avqust': 8,
          'sentyabr': 9, 'oktyabr': 10, 'noyabr': 11, 'dekabr': 12}
_M = '(' + '|'.join(MONTHS) + ')'
_NUM = r'(?:№\s*)?(\d+(?:/\d+)?(?:\s?[-–]\s?[A-Za-zƏəİıIVXQD]+)?)'
_SUF = r'(?:-?\s?c[ıiuü]|-?\s?[ıiuü]nc[ıiuü])?'
CITE_A = re.compile(r'(\d{1,2})\s+' + _M + r'[a-zıəüöç]*\s+(\d{4})' + _SUF + r'\s+il(?:in)?\s*(?:tarixli\s+)?' + _NUM +
                    r'\s*(?:nömrəli|saylı)', re.I)
CITE_B = re.compile(r'(\d{4})' + _SUF + r'\s+il(?:in)?\s+(\d{1,2})\s+' + _M + r'[a-zıəüöç]*\s+(?:tarixli\s+)?' + _NUM +
                    r'\s*(?:nömrəli|saylı)', re.I)
NOTE_MARK = re.compile(r'\[\^(\d+)\]')


# ---------------------------------------------------------------------------------------------------- cache

def jload(rel: str):
    p = CACHE / (rel + '.gz')
    return json.loads(gzip.decompress(p.read_bytes()).decode('utf-8')) if p.exists() else None


def html_raw(path: str) -> bytes | None:
    p = CACHE / 'html' / (path + '.gz')
    return gzip.decompress(p.read_bytes()) if p.exists() else None


def ddmmyyyy(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r'^(\d{2})[.-](\d{2})[.-](\d{4})$', s.strip())
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


# ---------------------------------------------------------------------------------------------------- citations

def norm_num(n: str) -> str:
    return re.sub(r'\s', '', n.replace('–', '-')).upper().replace('İ', 'I')


def cites_in_note(paras: list[str]) -> list[tuple[str, str]]:
    """(number, adoption date) of each act a note names as making a change. A note lists one change per paragraph,
    each starting with the act ("17 aprel 2007-ci il tarixli 315-IIIQD nömrəli ... Qanunu ilə ..."); the earlier
    wording it quotes ("... deyilirdi:") follows in paragraphs of its own. So the act of the first paragraph counts,
    and of every later paragraph that starts with an act's date (after an optional list number)."""
    out = []
    for i, para in enumerate(paras):
        head = para.split('deyilirdi')[0]
        best = None
        for rx, order in ((CITE_A, 'dmy'), (CITE_B, 'ydm')):
            m = rx.search(head)
            if not m or (best is not None and m.start() >= best[0]):
                continue
            if i > 0 and not re.fullmatch(r'[\s\d.)\-*]*', head[:m.start()]):
                continue
            if order == 'dmy':
                d, mo, y, num = m.group(1), m.group(2), m.group(3), m.group(4)
            else:
                y, d, mo, num = m.group(1), m.group(2), m.group(3), m.group(4)
            try:
                day = f'{int(y):04d}-{MONTHS[mo.lower()]:02d}-{int(d):02d}'
            except KeyError:
                continue
            best = (m.start(), (norm_num(num), day))
        if best and best[1] not in out:
            out.append(best[1])
    return out


# ---------------------------------------------------------------------------------------------------- parsing

def parsed_name(path: str) -> Path:
    return PARSED / (path.replace('/', '_') + '.json')


def parse_one(path: str) -> str:
    out = parsed_name(path)
    if out.exists():
        try:
            if json.loads(out.read_text('utf-8')).get('parser') == PARSER_VERSION:
                return path
        except (OSError, json.JSONDecodeError):
            pass
    raw = html_raw(path)
    try:
        if raw is None:
            raise FileNotFoundError('not in the cache')
        d = parse_text.parse(raw)
        files, cites = {}, {}

        def add(name, lines):
            t = parse_text.unit_text(lines, d['notes'])
            files[name] = t
            refs = []
            for ln in lines:
                refs += [int(x) for x in re.findall('\x01(\\d+)\x02', ln)]
            cs = []
            for r in dict.fromkeys(refs):
                for c in cites_in_note(d['notes'].get(r, [])):
                    if c not in cs:
                        cs.append(c)
            cites[name] = cs
        if d['title']:
            add('title.md', d['title'])
        for u in d['units']:
            add(f"madde-{u['id']}.md", u['lines'])
        if not d['units'] and not d['title']:
            raise ValueError('no text')
        rec = {'parser': PARSER_VERSION, 'files': files, 'cites': cites,
               'sha256': hashlib.sha256(raw).hexdigest()}
    except Exception as e:  # noqa: BLE001 - recorded, the edition is skipped
        rec = {'parser': PARSER_VERSION, 'error': f'{type(e).__name__}: {e}'}
    out.write_text(json.dumps(rec, ensure_ascii=False), 'utf-8')
    return path


def load_parsed(path: str) -> dict:
    return json.loads(parsed_name(path).read_text('utf-8'))


# ---------------------------------------------------------------------------------------------------- acts

def load_acts() -> list[dict]:
    acts = []
    index = json.loads(gzip.decompress((CACHE / 'index.json.gz').read_bytes()).decode('utf-8'))

    def jload(rel: str):
        kind, name = rel.split('/')
        return index[name.split('.')[0]][kind]
    for r in json.loads((CACHE / 'catalogue.json').read_text('utf-8')):
        meta = (jload(f"meta/{r['id']}.json") or {}).get('data') or {}
        req = meta.get('requisite') or {}
        a = {'id': r['id'], 'kind': r['kind'], 'title': (req.get('title') or r['title'] or '').strip(),
             'number': norm_num(req.get('citation') or r.get('citation') or ''),
             'status': req.get('statusName') or r.get('statusName') or '',
             'adopted': ddmmyyyy(req.get('acceptDate') or r.get('acceptDate')),
             'effective': ddmmyyyy(req.get('effectDate')),
             'html': (meta.get('htmlUrl') or '')[len(SITE):] if (meta.get('htmlUrl') or '').startswith(SITE) else '',
             'published': sorted(filter(None, (ddmmyyyy(f.get('fieldValue')) for f in req.get('fields') or []
                                               if f.get('fieldName') == 'Dərc olunma tarixi')))}
        if a['number'] in ('00', '0'):
            a['number'] = ''
        a['inforce'], a['basis'] = inforce_of(a)
        vers = (jload(f"versions/{r['id']}.json") or {}).get('data') or []
        eds = []
        for v in vers:
            hp = v.get('htmlPath') or ''
            name = hp.split('/')[-1]
            if not hp or name.startswith('f_'):
                continue
            m = re.match(r'^(?:v_\d+_(\d+)|c_(\d+))\.html$', name)
            if not m:
                continue
            order = (1, int(m.group(1))) if m.group(1) else (0, int(m.group(2)))
            eds.append({'path': 'versions/' + hp, 'order': order, 'date': ddmmyyyy(v.get('effectDate')),
                        'original': bool(m.group(2)) or m.group(1) == '1'})
        eds.sort(key=lambda e: e['order'])
        if eds:
            eds = [e for i, e in enumerate(eds) if i == 0 or e['order'] != eds[i - 1]['order']]
            eds[1:] = [dict(e, original=False) for e in eds[1:]]
        if a['html']:
            eds.append({'path': a['html'], 'order': (9, 0), 'date': None, 'original': False, 'current': True})
        a['editions'] = eds
        if a['status'] != INFORCE:
            rel = (jload(f"related/{r['id']}.json") or {}).get('data') or []
            a['repealed_by'] = [{'number': norm_num(x.get('citation') or ''), 'id': x['id'],
                                 'adopted': ddmmyyyy(x.get('acceptDate'))}
                                for x in rel if (x.get('relation') or '').startswith('Ləğv')]
        acts.append(a)
    acts.sort(key=lambda a: a['id'])
    return acts


def inforce_of(a: dict) -> tuple[str, str]:
    if a.get('effective'):
        return a['effective'], 'e-qanun in-force date'
    if a.get('published'):
        return a['published'][0], 'first official publication (e-qanun gives no in-force date)'
    if a.get('adopted'):
        return a['adopted'], 'adopted (e-qanun gives no in-force or publication date)'
    return '1991-10-18', 'unknown (no date in e-qanun; independence date used)'


class Resolver:
    """Maps a note's (number, adoption date) to an act record."""

    def __init__(self, acts: list[dict]):
        self.by_num: dict[str, list[dict]] = {}
        self.by_id = {a['id']: a for a in acts}
        for a in acts:
            if a['number']:
                self.by_num.setdefault(a['number'], []).append(a)
        self.referendum = {(a['adopted'] or '')[:4]: a for a in acts if a['kind'] == 'referendum-act'}

    def act(self, num: str, day: str, law: dict) -> dict:
        cands = self.by_num.get(num, [])
        exact = [a for a in cands if a['adopted'] == day]
        if exact or len(cands) == 1 and re.search(r'[A-Z]', num):
            return self.record(exact[0] if exact else cands[0])
        if law['kind'] == 'constitution' and day[:4] in self.referendum:
            r = self.record(self.referendum[day[:4]])
            return dict(r, via=f'{num} ({day}), the Central Election Commission decision on the referendum result')
        return {'key': f'x:{num}:{day}', 'id': None, 'number': num, 'adopted': day, 'title': '',
                'inforce': day, 'basis': 'adopted (the act is not in the e-qanun list of laws)', 'published': [],
                'kind': 'other'}

    def record(self, a: dict) -> dict:
        return {'key': f"id:{a['id']}", 'id': a['id'], 'number': a['number'], 'adopted': a['adopted'],
                'title': a['title'], 'inforce': a['inforce'], 'basis': a['basis'], 'published': a['published'],
                'kind': a['kind']}


# ---------------------------------------------------------------------------------------------------- merge

def merge3(base: list[str], new: list[str], cur: list[str]) -> list[str] | None:
    """Apply the change base -> new onto cur, line by line, or None if the lines it touches are not in cur as they
    were in base."""
    if base == cur:
        return list(new)
    m: dict[int, int] = {}
    for a, b, size in difflib.SequenceMatcher(None, base, cur, autojunk=False).get_matching_blocks():
        for t in range(size):
            m[a + t] = b + t
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        if i2 > i1:
            if i1 not in m or any(m.get(i1 + t) != m[i1] + t for t in range(i2 - i1)):
                return None
            c1, c2 = m[i1], m[i1] + (i2 - i1)
        else:
            if i1 == 0:
                c1 = 0
            elif (i1 - 1) in m:
                c1 = m[i1 - 1] + 1
            elif i1 in m:
                c1 = m[i1]
            else:
                return None
            c2 = c1
        edits.append((c1, c2, new[j1:j2]))
    out = list(cur)
    last = None
    for c1, c2, rep in sorted(edits, reverse=True):
        if last is not None and c2 > last:
            return None
        out[c1:c2] = rep
        last = c1
    return out


def lines(t: str | None) -> list[str]:
    return [] if t is None else t.split('\n')


def unlines(ls: list[str]) -> str | None:
    t = '\n'.join(ls)
    return t if t.strip() else None


def squash(s: str | None) -> str | None:
    return None if s is None else re.sub(r'\s+', '', s)



# ---------------------------------------------------------------------------------------------------- hunks

def split_rendered(t: str | None) -> tuple[list[str], dict[int, list[str]]]:
    """A built file -> (text lines, {note number: note lines})."""
    if t is None:
        return [], {}
    body, sep, notes_part = t.rstrip('\n').partition('\n\n[^1]: ')
    lines_ = body.split('\n')
    notes: dict[int, list[str]] = {}
    if sep:
        cur = None
        for ln in ('[^1]: ' + notes_part).split('\n'):
            m = re.match(r'^\[\^(\d+)\]: (.*)$', ln)
            if m:
                cur = int(m.group(1))
                notes[cur] = [m.group(2)]
            elif cur is not None:
                notes[cur].append(ln[4:] if ln.startswith('    ') else ln)
    return lines_, notes


def render_mixed(items: list[tuple[str, dict[int, list[str]]]]) -> str:
    """Lines that each come with their own version's notes -> one file, notes renumbered in order of first mark."""
    order: list[tuple] = []
    out = []
    for ln, notes in items:
        def sub(m, notes=notes):
            body = tuple(notes.get(int(m.group(1))) or ['(note text missing in the source)'])
            if body not in order:
                order.append(body)
            return f'[^{order.index(body) + 1}]'
        out.append(NOTE_MARK.sub(sub, ln))
    if order:
        out.append('')
        for k, body in enumerate(order, 1):
            out.append(f'[^{k}]: {body[0]}')
            out += ['    ' + b for b in body[1:]]
    return '\n'.join(out) + '\n'


def split_file(old: str | None, new: str | None, nw: dict, new_cites: list, resolve) -> list:
    """A file whose notes newly name several acts: credit each changed block of lines to the one act its new note
    marks name. Returns [(group key, group fields, evidence, text after this step)], in date order; the last text is
    exactly `new`. Blocks with no mark, or with marks naming several acts, form a final labelled step (Kind: several)."""
    ol, on = split_rendered(old)
    nl, nn = split_rendered(new)
    want = set(new_cites)

    def acts_of(lines_):
        keys = {}
        for ln in lines_:
            for m in NOTE_MARK.finditer(ln):
                cs = [c for c in cites_in_note(nn.get(int(m.group(1)), [])) if c in want]
                keys.update(resolve(cs))
        return keys

    def strip(ls):
        return [NOTE_MARK.sub('', x) for x in ls]
    by_act: dict[str, list] = {}
    rest = []
    rest_acts: dict[str, dict] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, strip(ol), strip(nl), autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        ks = acts_of(nl[j1:j2])
        if len(ks) == 1 and next(iter(ks)) in nw:
            by_act.setdefault(next(iter(ks)), []).append((i1, i2, j1, j2))
        else:
            rest.append((i1, i2, j1, j2))
            rest_acts.update({k: v for k, v in ks.items() if k in nw})
    order = sorted(by_act, key=lambda k: (nw[k]['inforce'], k))
    if not order:
        day = max(a['inforce'] for a in nw.values())
        return [(('several', day, tuple(sorted(nw))), {'kind': 'several', 'act': None, 'candidates': nw,
                                                       'date': day},
                 'e-qanun notes name several acts', new)]
    steps = []
    done: list = []
    for idx, k in enumerate(order):
        done += by_act[k]
        if idx == len(order) - 1 and not rest:
            text = new
        else:
            items, pos = [], 0
            for i1, i2, j1, j2 in sorted(done):
                items += [(x, on) for x in ol[pos:i1]]
                items += [(x, nn) for x in nl[j1:j2]]
                pos = i2
            items += [(x, on) for x in ol[pos:]]
            text = render_mixed(items) if any(x.strip() for x, _ in items) else None
        a = nw[k]
        steps.append((('act', a['key']), {'kind': 'amendment', 'act': a, 'date': a['inforce']},
                      'e-qanun note on the changed lines', text))
    if rest:
        cands = rest_acts or {k: v for k, v in nw.items() if k not in by_act} or nw
        day = max([a['inforce'] for a in cands.values()] + [nw[order[-1]]['inforce']])
        steps.append((('several', day, tuple(sorted(cands))), {'kind': 'several', 'act': None, 'candidates': cands,
                                                          'date': day},
                      'e-qanun notes name several acts', new))
    return steps


# ---------------------------------------------------------------------------------------------------- planning

def plan_law(law: dict, res: Resolver) -> tuple[list[dict], list[dict]]:
    """Events for one act and the issues met. An event: {n, date, kind, act, changes{path: text|None}, ...}."""
    issues = []
    d = f"{law['kind']}/{law['id']}"
    own = res.record(law)
    eds = []
    for e in law['editions']:
        p = load_parsed(e['path'])
        if p.get('error'):
            issues.append({'law': law['id'], 'text': e['path'], 'issue': p['error']})
            continue
        eds.append((e, {f'{d}/{k}': v for k, v in p['files'].items()},
                    {f'{d}/{k}': [tuple(c) for c in v] for k, v in p['cites'].items()}))
    if not eds:
        return [], issues

    def resolve(cs):
        out = {}
        for num, day in cs:
            if law['number'] and num == law['number']:
                continue
            r = res.act(num, day, law)
            out.setdefault(r['key'], r)
        return out

    pubs = []        # (event, files) in source order; files is the full state after the event
    e0, files0, cites0 = eds[0]
    if e0['original']:
        pubs.append(({'kind': 'original', 'act': own, 'date': own['inforce'], 'evidence': 'e-qanun original text',
                      'source': e0['path']}, dict(files0)))
    else:
        plain = {p: t for p, t in files0.items() if not resolve(cites0.get(p, []))}
        state = dict(plain)
        pubs.append(({'kind': 'original', 'act': own, 'date': own['inforce'],
                      'evidence': 'files with no amendment note in a later consolidation', 'source': e0['path'],
                      'partial': len(files0) - len(plain)}, dict(state)))
        groups: dict[str, dict] = {}
        for p in sorted(set(files0) - set(plain)):
            acts = resolve(cites0.get(p, []))
            day = max(max(a['inforce'] for a in acts.values()), own['inforce'])
            g = groups.setdefault(day, {'files': [], 'acts': {}})
            g['files'].append(p)
            g['acts'].update(acts)
        for day in sorted(groups):
            g = groups[day]
            for p in g['files']:
                state[p] = files0[p]
            pubs.append(({'kind': 'baseline', 'act': None, 'date': day, 'candidates': g['acts'],
                          'evidence': 'consolidation; earlier wording not in the source', 'source': e0['path']},
                         dict(state)))
    prev_files, prev_cites, prev_date = files0, cites0, e0.get('date') or own['inforce']
    for e, files, cites in eds[1:]:
        delta = {}
        for p in sorted(set(files) | set(prev_files)):
            a, b = prev_files.get(p), files.get(p)
            if a != b:
                delta[p] = b
        if not delta:
            prev_files, prev_cites = files, cites
            prev_date = e.get('date') or prev_date
            continue
        new_by_file = {}
        edition_new: dict[str, dict] = {}
        for p in delta:
            old = set(prev_cites.get(p, []))
            nw = resolve([c for c in cites.get(p, []) if c not in old])
            new_by_file[p] = nw
            edition_new.update(nw)
        if e.get('current'):
            day_ed = max([a['inforce'] for a in edition_new.values()] + [prev_date])
        else:
            day_ed = e.get('date') or prev_date
        groups: dict[tuple, dict] = {}

        def grp(key, **kw):
            return groups.setdefault(key, dict(kw, steps={}, evidence=set()))
        for p in delta:
            nw = new_by_file[p]
            if len(nw) == 1:
                a = next(iter(nw.values()))
                g = grp(('act', a['key']), kind='amendment', act=a, date=a['inforce'])
                g['evidence'].add('e-qanun note')
                g['steps'][p] = files.get(p)
            elif not nw and len(edition_new) == 1:
                a = next(iter(edition_new.values()))
                g = grp(('act', a['key']), kind='amendment', act=a, date=a['inforce'])
                g['evidence'].add('e-qanun edition')
                g['steps'][p] = files.get(p)
            elif not nw:
                g = grp(('unexplained',), kind='unexplained', act=None, date=day_ed)
                g['evidence'].add('date of the e-qanun edition')
                g['steps'][p] = files.get(p)
            else:
                old = set(prev_cites.get(p, []))
                for key, kw, ev, text in split_file(prev_files.get(p), files.get(p), nw,
                                                    [c for c in cites.get(p, []) if c not in old], resolve):
                    g = grp(key, **kw)
                    if key[0] == 'several':
                        g.setdefault('candidates', {}).update(kw['candidates'])
                    g['evidence'].add(ev)
                    g['steps'][p] = text
        state = dict(prev_files)
        for key in sorted(groups, key=lambda k: (groups[k]['date'], k)):
            g = groups[key]
            for p, text in g['steps'].items():
                if text is None:
                    state.pop(p, None)
                else:
                    state[p] = text
            ev = {'kind': g['kind'], 'act': g['act'], 'date': g['date'], 'source': e['path'],
                  'evidence': ', '.join(sorted(g['evidence']))}
            if g.get('candidates'):
                ev['candidates'] = g['candidates']
            pubs.append((ev, dict(state)))
        prev_files, prev_cites = files, cites
        prev_date = e.get('date') or day_ed
    # Repeal.
    if law['status'] != INFORCE and law.get('repealed_by'):
        rb = law['repealed_by'][0]
        a = res.record(res.by_id[rb['id']]) if rb['id'] in res.by_id else \
            res.act(rb['number'], rb['adopted'] or '1991-01-01', law)
        pubs.append(({'kind': 'repeal', 'act': a, 'date': a['inforce'], 'evidence': 'e-qanun related acts',
                      'source': law['html']}, {}))
    events = replay(law, pubs, own, issues)
    for ev in events:
        ev['law'] = {k: law[k] for k in ('id', 'kind', 'title', 'number', 'adopted')}
        if ev.get('act'):
            ev['act_key'] = ev['act']['key']
    return events, issues


def replay(law: dict, pubs: list[tuple[dict, dict]], own: dict, issues: list) -> list[dict]:
    """Apply the publications in in-force order (see the Georgia builder): out-of-order changes are re-applied by a
    three-way line merge onto the text then in force, or held back to the commit that completes the run."""
    hist: dict[str, tuple[list, list]] = {}
    deltas: dict[int, dict] = {}
    prev: dict[str, str] = {}
    for n, (ev, files) in enumerate(pubs):
        delta = {}
        for p in set(files) | set(prev):
            a, b = prev.get(p), files.get(p)
            if a != b:
                delta[p] = b
        deltas[n] = delta
        for p, t in delta.items():
            ns, ts = hist.setdefault(p, ([], []))
            ns.append(n)
            ts.append(t)
        prev = files
        ev['n'] = n
        ev['date'] = max(ev['date'], own['inforce']) if ev['kind'] != 'repeal' else ev['date']
        if ev['date'] != (ev['act'] or {}).get('inforce', ev['date']):
            ev['clamped_from'] = (ev['act'] or {}).get('inforce')

    def text_at(p: str, n: int) -> str | None:
        ns, ts = hist.get(p, ([], []))
        i = bisect.bisect_right(ns, n) - 1
        return ts[i] if i >= 0 else None

    events = [ev for ev, _ in pubs]
    order = sorted(events, key=lambda e: (e['date'], e['n']))
    nset = list(range(len(pubs)))
    state: dict[str, str] = {}
    applied: set[int] = set()
    out = []
    prev_k = -1
    pending: set[tuple[int, str]] = set()
    repealed = False
    for e in order:
        if repealed:
            e['changes'], e['held_from'] = {}, []
            out.append(e)
            continue
        applied.add(e['n'])
        k = -1
        for n in nset:
            if n in applied:
                k = n
            else:
                break
        beyond = sorted(n for n in applied if n > k)
        touched = set(deltas[e['n']])
        for n in beyond:
            touched |= set(deltas[n])
        for n in nset:
            if prev_k < n <= k:
                touched |= set(deltas[n])
        prev_k = k
        held = []
        changes_out: dict[str, str | None] = {}
        for p in sorted(touched):
            want = lines(text_at(p, k)) if k >= 0 else []
            for n in beyond:
                if p not in deltas[n]:
                    continue
                r = merge3(lines(text_at(p, n - 1)), lines(text_at(p, n)), want)
                if r is None:
                    held.append((n, p))
                else:
                    want = r
            t = unlines(want)
            if t is not None and not t.endswith('\n'):
                t += '\n'
            if t != state.get(p):
                changes_out[p] = t
                if t is None:
                    state.pop(p, None)
                else:
                    state[p] = t
        if e['kind'] == 'repeal':
            repealed = True
            for p in list(state):
                changes_out[p] = None
                state.pop(p)
        e['changes'] = changes_out
        e['held_from'] = sorted((n, p) for n, p in pending if n <= k)
        pending = {(n, p) for n, p in pending if n > k and p not in touched} | set(held)
        out.append(e)
    by_n = {e['n']: e for e in out}
    for e in out:
        for n, p in e['held_from']:
            by_n[n].setdefault('held_back', []).append(p)
        e['held_from'] = [(label_of(by_n[n]), p) for n, p in e['held_from']]
    final = {p: text_at(p, nset[-1]) for p in hist}
    final = {p: t for p, t in final.items() if t is not None}
    if out and not repealed and json.dumps(state, sort_keys=True) != json.dumps(final, sort_keys=True):
        issues.append({'law': law['id'], 'text': '', 'issue': 'replayed text differs from the last text'})
    return [e for e in out if e['changes'] or e['kind'] == 'original']


def label_of(e: dict) -> str:
    if e.get('act'):
        return e['act']['number'] or e['act']['key']
    return f"{e['kind']} {e['date']}"


def plan_worker(args):
    law, res = args
    return plan_law(law, res)


_RES = None


def _init(acts):
    global _RES
    _RES = Resolver(acts)


def _plan(law):
    return plan_law(law, _RES)


# ---------------------------------------------------------------------------------------------------- commits

def group(events: list[dict]) -> list[dict]:
    commits: dict[tuple, dict] = {}
    # An act whose events in one law on one day are interrupted by another commit (a labelled step, or another act)
    # gets a second commit that day for the later events, so the day's commits can keep every law's order.
    run: dict[tuple, tuple] = {}         # (law, date) -> last act key seen
    occ: dict[tuple, int] = {}           # (law, date, act) -> occurrence index
    for e in events:
        if e['kind'] in ('amendment', 'repeal', 'original'):
            ld = (e['law']['id'], e['date'])
            ak = e['act']['key']
            if (*ld, ak) in occ and run.get(ld) != ak:
                occ[(*ld, ak)] += 1
            occ.setdefault((*ld, ak), 0)
            run[ld] = ak
            k = (e['date'], 1, ak, f"{occ[(*ld, ak)]:03d}")
        else:
            run[(e['law']['id'], e['date'])] = None
            k = (e['date'], 2, e['kind'], f"{e['law']['id']:08d}-{e['n']:05d}")
        c = commits.setdefault(k, {'date': e['date'], 'act': e.get('act'), 'parts': []})
        c['parts'].append(e)
    # Within one day, a law's events must keep their order (a repeal after the day's other change to that law, a
    # labelled step after the act steps of the same file). Order the day's commits topologically by those pairs, ties
    # by key; a cycle (two acts in opposite orders in two laws) is broken by key and counted.
    key_of = {}
    for k, c in commits.items():
        for p in c['parts']:
            key_of[id(p)] = k
    after: dict[tuple, set] = {k: set() for k in commits}
    last_by_law: dict[int, dict] = {}
    for e in events:
        k = key_of[id(e)]
        prev = last_by_law.get(e['law']['id'])
        if prev is not None and prev[0] == k[0] and prev != k:
            after[k].add(prev)
        last_by_law[e['law']['id']] = k
    order = []
    import heapq
    cycles = 0
    by_day: dict[str, list] = {}
    for k in commits:
        by_day.setdefault(k[0], []).append(k)
    for day in sorted(by_day):
        ks = set(by_day[day])
        need = {k: {x for x in after[k] if x in ks} for k in ks}
        ready = [k for k in ks if not need[k]]
        heapq.heapify(ready)
        done = set()
        while len(done) < len(ks):
            if not ready:
                cycles += 1
                k = min(k for k in ks if k not in done)
                need[k] = set()
                heapq.heappush(ready, k)
            k = heapq.heappop(ready)
            if k in done:
                continue
            done.add(k)
            order.append(k)
            for x in ks:
                if x not in done and k in need[x]:
                    need[x].discard(k)
                    if not need[x]:
                        heapq.heappush(ready, x)
    if cycles:
        print(f'  {cycles} same-day ordering cycles broken by key', flush=True)
    out = []
    for k in order:
        c = commits[k]
        kinds = {p['kind'] for p in c['parts']}
        c['kind'] = next(x for x in ('amendment', 'repeal', 'original', 'baseline', 'several', 'unexplained')
                         if x in kinds)
        c['parts'].sort(key=lambda p: (p['law']['id'], p['n']))
        out.append(c)
    return out


def short(s: str, n: int) -> str:
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


KIND_NAME = {'law': 'Qanun', 'code': 'Qanun', 'constitutional-law': 'Konstitusiya Qanunu',
             'referendum-act': 'Referendum aktı', 'constitution': 'Konstitusiya', 'other': 'Akt'}


def slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower().translate(str.maketrans('əıöüçşğİ', 'eioucsgi'))).strip('-') or 'x'


def author_of(a: dict) -> tuple[str, str]:
    adopted = a.get('adopted') or ''
    dd = f'{adopted[8:10]}.{adopted[5:7]}.{adopted[:4]}' if adopted else ''
    if not a.get('number'):
        # Codes, the Constitution and referendum acts have no number of their own: they are named by title.
        title = re.sub(r'^Azərbaycan Respublikasının\s+', '', (a.get('title') or '').strip())
        name = f"{short(title or KIND_NAME.get(a['kind'], 'Akt'), 60)} ({dd})"
        email = f"{slug(a['kind'])}-{adopted.replace('-', '')}@e-qanun.invalid"
    else:
        name = f"{KIND_NAME.get(a['kind'], 'Akt')} {a['number']} ({dd})"
        email = f"{slug(a['number'])}-{adopted.replace('-', '')}@e-qanun.invalid"
    if a.get('id'):
        email = email.replace('@', f"-{a['id']}@")
    return name, email


def law_label(law: dict) -> str:
    return short(law['title'], 60)


def act_source(a: dict) -> str:
    return f"{SITE}framework/{a['id']}" if a.get('id') else ''


def message(c: dict) -> tuple[str, str]:
    parts = c['parts']
    laws = []
    for p in parts:
        if p['law']['id'] not in [l['id'] for l in laws]:
            laws.append(p['law'])
    nfiles = sum(len(p['changes']) for p in parts)
    kind = c['kind']
    trailers = [f'Kind: {kind}', f"In-force: {c['date']}"]
    if kind in ('amendment', 'repeal', 'original'):
        a = c['act']
        name, email = author_of(a)
        trailers.append(f"In-force-basis: {a['basis']}")
        if a['inforce'] != c['date']:
            trailers.append(f"In-force-act: {a['inforce']}")
        if a.get('adopted'):
            trailers.append(f"Adopted: {a['adopted']}")
        for d in a.get('published') or []:
            trailers.append(f'Published: {d}')
            break
        if a.get('id'):
            trailers.append(f"Act: {a['id']}")
            trailers.append(f'Source: {act_source(a)}')
        if a.get('via'):
            trailers.append(f"Via: {a['via']}")
        own = [p for p in parts if p['kind'] == 'original']
        other = [p for p in parts if p['kind'] != 'original']
        title = a.get('title') or (own[0]['law']['title'] if own else '')
        lead = f"{a['number']}: " if a.get('number') else ''
        if other:
            what = 'repeals' if any(p['kind'] == 'repeal' for p in other) else 'amends'
            names = [law_label(p['law']) for p in other]
            subject = short(f"{lead}{what} {', '.join(dict.fromkeys(names))}", 72)
        else:
            subject = short(f'{lead}{title}', 72)
        body = [short(title, 2000) or '(title not in e-qanun)', '']
        if own:
            p = own[0]
            if p.get('partial'):
                body.append(f"The act's own text as it took effect: {len(p['changes'])} file(s). e-qanun keeps only a "
                            f"later consolidation of this act; {p['partial']} file(s) carrying amendment notes appear "
                            'from the date of the latest act they cite (Kind: baseline commits).')
            else:
                body.append(f"The act's own text as it took effect: {len(p['changes'])} file(s).")
        if other:
            body.append(f"{'Repeal of' if any(p['kind'] == 'repeal' for p in other) else 'Changes to'} "
                        f"{len({p['law']['id'] for p in other})} act(s), "
                        f"{sum(len(p['changes']) for p in other)} file(s).")
        ev = sorted({p['evidence'] for p in parts})
        for x in ev:
            trailers.append(f'Evidence: {x}')
        for p in parts:
            trailers.append(f"Affecting: {p['law']['id']} | {short(p['law']['title'], 120)}")
    else:
        name, email = PUBLISHER
        law = laws[0]
        p = parts[0]
        if kind == 'baseline':
            subject = short(f"{law_label(law)}: consolidated text, earlier wording not kept", 72)
            body = [law['title'], '',
                    f"e-qanun keeps only a later consolidation of this act. These {nfiles} file(s) carry notes naming "
                    'the acts below; their wording before those acts is not in the source, so they appear here, on the '
                    'in-force date of the latest of them. Credited to no act.']
        elif kind == 'several':
            subject = short(f"{law_label(law)}: change notes name several acts", 72)
            body = [law['title'], '',
                    f"These {nfiles} file(s) changed between two e-qanun editions, and their notes newly name more "
                    'than one act, so the change is credited to none of them. Dated by the latest of them.']
        else:
            subject = short(f"{law_label(law)}: change no act is named for", 72)
            body = [law['title'], '',
                    f"These {nfiles} file(s) differ between two e-qanun editions, but no note names an act for the "
                    'change. Dated by the e-qanun edition.']
        for x in sorted({q['evidence'] for q in parts}):
            trailers.append(f'Evidence: {x}')
        cands = {}
        for q in parts:
            cands.update(q.get('candidates') or {})
        for k in sorted(cands, key=lambda k: (cands[k]['inforce'], k)):
            a = cands[k]
            trailers.append(f"Candidate: {a['number'] or a['key']} | adopted {a['adopted']} | in force {a['inforce']}")
        trailers.append(f"Affecting: {law['id']} | {short(law['title'], 120)}")
        trailers.append(f"Source: {SITE}{p['source']}")
    for p in parts:
        for path in sorted(p.get('held_back', ())):
            trailers.append(f'Held-back: {path}')
        for n, path in p.get('held_from', []):
            trailers.append(f'Includes-held-back: {n} | {path}')
    if any(p.get('held_back') for p in parts):
        body += ['', "Some of these changes could not be separated from a change that took effect later; they appear "
                 "in that commit (Held-back: lines)."]
    msg = '\n'.join([subject, '', *body, '', *trailers]) + '\n'
    return f'{name} <{email}>', msg


# ---------------------------------------------------------------------------------------------------- write

def stamp(day: str, seq: int) -> str:
    d = datetime.strptime(min(day, '2099-12-31'), '%Y-%m-%d').replace(hour=12)
    ts = int((d - timedelta(hours=4)).replace(tzinfo=timezone.utc).timestamp()) if d.year >= 1970 else seq
    return f'{ts} +0400'


def write_commit(w, ref: str, mark: int, parent: int | None, c: dict, seq: int) -> None:
    author, msg = message(c)
    when = stamp(c['date'], seq)
    w(f'commit {ref}\nmark :{mark}\nauthor {author} {when}\ncommitter {COMMITTER} {when}\n'.encode())
    m = msg.encode('utf-8')
    w(f'data {len(m)}\n'.encode() + m + b'\n')
    if parent:
        w(f'from :{parent}\n'.encode())
    for p in c['parts']:
        for path, text in sorted(p['changes'].items()):
            if text is None:
                w(f'D {path}\n'.encode())
            else:
                t = text.encode('utf-8')
                w(f'M 100644 inline {path}\ndata {len(t)}\n'.encode() + t + b'\n')
    w(b'\n')


def fast_import(repo: Path, commits: list[dict], docs: dict[str, bytes], today: str, docs_date: str) -> None:
    proc = subprocess.Popen(['git', '-C', str(repo), 'fast-import', '--quiet', '--force', '--done'],
                            stdin=subprocess.PIPE)
    w = proc.stdin.write
    mark = 0
    main_mark = None
    seq = 0
    for c in commits:
        if c['date'] > today:
            continue
        seq += 1
        mark += 1
        write_commit(w, 'refs/heads/main', mark, main_mark, c, seq)
        main_mark = mark
    seq += 1
    mark += 1
    when = stamp(docs_date, seq)
    msg = (f'Documentation: README, REPRODUCE, corpus.json, tools and laws.csv\n\nBuilt from the e-qanun.az cache '
           f'retrieved on {docs_date}.\n\nKind: documentation\nIn-force: {docs_date}\n').encode()
    w(f'commit refs/heads/main\nmark :{mark}\nauthor {COMMITTER} {when}\ncommitter {COMMITTER} {when}\n'.encode())
    w(f'data {len(msg)}\n'.encode() + msg + b'\n')
    w(f'from :{main_mark}\n'.encode())
    for path, data in sorted(docs.items()):
        w(f'M 100644 inline {path}\ndata {len(data)}\n'.encode() + data + b'\n')
    w(b'\n')
    prev = mark
    for c in commits:
        if c['date'] <= today:
            continue
        seq += 1
        mark += 1
        write_commit(w, 'refs/heads/future', mark, prev, c, seq)
        prev = mark
    w(b'done\n')
    proc.stdin.close()
    if proc.wait():
        sys.exit('git fast-import failed')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('repo', type=Path)
    ap.add_argument('--today', required=True, help='the build day: commits in force after it go on `future`')
    ap.add_argument('--docs-date', help='date of the documentation commit (default: --today)')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--only', help='comma-separated e-qanun ids (testing)')
    ap.add_argument('--parse-only', action='store_true')
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args()
    PARSED.mkdir(parents=True, exist_ok=True)
    acts = load_acts()
    corpus = acts
    if args.only:
        keep = {int(x) for x in args.only.split(',')}
        corpus = [a for a in acts if a['id'] in keep]
    # A repealed act for which e-qanun names no repealing act has no date to leave the tree on; it is left out (and
    # listed) rather than shown as in force for ever.
    left_out = [a for a in corpus if a['status'] != INFORCE and not a.get('repealed_by')]
    corpus = [a for a in corpus if not (a['status'] != INFORCE and not a.get('repealed_by'))]
    paths = sorted({e['path'] for a in corpus for e in a['editions']})
    print(f'{len(corpus)} acts, {len(paths)} texts', flush=True)
    with ProcessPoolExecutor(args.workers) as pool:
        for i, _ in enumerate(pool.map(parse_one, paths, chunksize=4), 1):
            if i % 2000 == 0:
                print(f'  parsed {i}/{len(paths)}', flush=True)
    if args.parse_only:
        return
    issues: list[dict] = [{'law': a['id'], 'text': '', 'issue': 'left out: repealed, but e-qanun names no repealing act'}
                          for a in left_out]
    events = []
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(acts,)) as pool:
        for evs, iss in pool.map(_plan, corpus, chunksize=8):
            events.extend(evs)
            issues.extend(iss)
    commits = group(events)
    future = sum(1 for c in commits if c['date'] > args.today)
    print(f'{len(commits)} commits ({future} future) from {len(events)} events; {len(issues)} issues', flush=True)
    (CACHE / 'issues.json').write_text(json.dumps(issues, ensure_ascii=False, indent=1), 'utf-8')
    if args.no_write:
        return
    import docs as docmod
    docs_date = args.docs_date or args.today
    docs = docmod.render(corpus, commits, issues, args.today)

    repo = args.repo
    repo.mkdir(parents=True, exist_ok=True)
    remote = None
    if (repo / '.git').exists():
        r = subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', 'origin'], capture_output=True, text=True)
        remote = r.stdout.strip() or None
        import os
        import shutil
        import stat

        def onerr(func, path, _):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(repo / '.git', onerror=onerr)
        for child in repo.iterdir():
            shutil.rmtree(child, onerror=onerr) if child.is_dir() else child.unlink()
    elif any(repo.iterdir()):
        sys.exit(f'{repo} is not empty and not an earlier build; refusing to write into it')
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.autocrlf', 'false'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.quotepath', 'false'], check=True)
    if remote:
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', remote], check=True)
    fast_import(repo, commits, docs, args.today, docs_date)
    subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '-f', 'main'], check=True)
    head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    count = subprocess.run(['git', '-C', str(repo), 'rev-list', '--count', 'HEAD'], capture_output=True,
                           text=True).stdout.strip()
    print(f'built {repo}: {count} commits on main, head {head}', flush=True)


if __name__ == '__main__':
    main()
