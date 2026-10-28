"""README, REPRODUCE.md, LICENSE, laws.csv, corpus.json, data/ and tools/ for the Azerbaijan law repository."""
import csv
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
REPO_FILES = HERE / 'repo'
CACHE = HERE / '.cache'
SCRIPTS = ('eqanun.py', 'fetch.py', 'parse_text.py', 'build.py', 'docs.py', 'check_repo.py', 'test_repo.py')


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def text_sums(acts: list[dict]) -> str:
    import build
    out = []
    for path in sorted({e['path'] for a in acts for e in a['editions']}):
        try:
            rec = build.load_parsed(path)
        except OSError:
            continue
        if rec.get('sha256'):
            out.append(f"{path}\t{rec['sha256']}\n")
    return ''.join(out)


def render(acts: list[dict], commits: list[dict], issues: list[dict], today: str) -> dict[str, bytes]:
    from build import author_of
    main = [c for c in commits if c['date'] <= today]
    future = [c for c in commits if c['date'] > today]
    kinds = Counter(c['kind'] for c in main)
    pkinds = Counter(p['kind'] for c in main for p in c['parts'])
    types = Counter(a['kind'] for a in acts)
    texts = sum(len(a['editions']) for a in acts)
    first = min(c['date'] for c in main) if main else ''
    last = max(c['date'] for c in main) if main else ''
    authors = {c['act']['key'] for c in main if c['kind'] in ('amendment', 'repeal')}
    ev = Counter(p['evidence'] for c in main for p in c['parts'] if p['kind'] == 'amendment')
    with_original = sum(1 for a in acts if a['editions'] and a['editions'][0]['original'])
    repealed = sum(1 for a in acts if a['status'] != 'Qüvvədədir')

    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow(['id', 'kind', 'title', 'number', 'adopted', 'in_force', 'in_force_basis', 'status', 'texts',
                'original_kept', 'path', 'source'])
    for a in acts:
        w.writerow([a['id'], a['kind'], a['title'], a['number'], a['adopted'] or '', a['inforce'], a['basis'],
                    a['status'], len(a['editions']), 'yes' if a['editions'] and a['editions'][0]['original'] else 'no',
                    f"{a['kind']}/{a['id']}/", f"https://e-qanun.az/framework/{a['id']}"])
    laws_csv = out.getvalue()

    iss = io.StringIO()
    w = csv.writer(iss, lineterminator='\n')
    w.writerow(['law', 'text', 'issue'])
    for i in sorted(issues, key=lambda i: (i['law'], i['text'], i['issue'])):
        w.writerow([i['law'], i['text'], i['issue']])

    stats = {
        'today': today, 'acts': len(acts), 'constitutions': types['constitution'], 'codes': types['code'],
        'laws_ordinary': types['law'], 'constitutional_laws': types['constitutional-law'],
        'referendum_acts': types['referendum-act'], 'repealed': repealed, 'texts': texts,
        'with_original': with_original, 'commits': len(main) + 1, 'future_commits': len(future),
        'c_amendment': kinds['amendment'], 'c_original': kinds['original'], 'c_repeal': kinds['repeal'],
        'c_baseline': kinds['baseline'], 'c_several': kinds['several'], 'c_unexplained': kinds['unexplained'],
        'p_amendment': pkinds['amendment'], 'amending_acts': len(authors), 'first': first, 'last': last,
        'issues': len(issues), 'in_force_from_publication': sum(1 for a in acts if a['basis'].startswith('first official')),
        'evidence_note': ev['e-qanun note'], 'evidence_edition': ev['e-qanun edition'],
        'evidence_lines': sum(v for k, v in ev.items() if 'changed lines' in k),
    }
    sums = text_sums(acts)
    stats['texts_sha256'] = _sha(sums.encode())
    tool_versions = {
        'python': sys.version.split()[0],
        'git': subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip(),
    }

    def fill(t: str) -> str:
        for k, v in stats.items():
            t = t.replace('{{' + k.upper() + '}}', str(v))
        for name in SCRIPTS:
            t = t.replace('{{SHA_' + name.upper().replace('.', '_') + '}}', _sha((HERE / name).read_bytes()))
        for k, v in tool_versions.items():
            t = t.replace('{{V_' + k.upper() + '}}', v)
        return t

    corpus = {
        'corpus': 'az/national/acts',
        'name': 'Legislation of the Republic of Azerbaijan (Constitution, referendum acts, constitutional laws, codes '
                'and laws)',
        'label': 'Azerbaijan',
        'language': 'az',
        'acts': {'constitution': types['constitution'], 'referendum_acts': types['referendum-act'],
                 'constitutional_laws': types['constitutional-law'], 'codes': types['code'], 'laws': types['law']},
        'history': 'in-force',
        'history_from': first,
        'record_to': last,
        'record_note': (f'e-qanun.az texts retrieved {today}. Dated editions are kept by e-qanun mostly from 2021; '
                        'before an act\'s first kept edition, articles that carry amendment notes appear only from '
                        'the in-force date of the latest act they cite (Kind: baseline).'),
        'checked_on': today,
        'built': today,
        'in_force_trailer': 'In-force',
        'baseline_trailer': 'Kind: baseline',
        'has_future_branch': 'future',
        'future_branch': 'future',
        'dates': {'commit': 'in-force (e-qanun requisite "effectDate" of the act that made the change; first '
                            'official publication where e-qanun gives none)',
                  'other_trailers': ['Adopted', 'Published', 'In-force-act'], 'time': '12:00 Asia/Baku (+0400)',
                  'before_1970': 'clamped to 1970-01-01 (none in this corpus)',
                  'future': 'branch future, never merged'},
        'author': {'amendment': 'the act named by e-qanun\'s note on the changed text',
                   'original': 'the act itself', 'publisher_kinds': ['baseline', 'several', 'unexplained'],
                   'evidence_trailer': 'Evidence'},
        'scope': {
            'trailer': 'Applies',
            'groups': 'any one line',
            'conditions': 'all of a line',
            'when_absent': 'no scope note extracted; not a statement that the change reaches every case',
            'default_reach': {
                'rule': 'no retroactive effect unless the act says so; never to establish or aggravate liability',
                'meaning': 'a normative legal act applies to relations arising after it takes effect; laws that '
                           'establish or aggravate legal liability have no retroactive force, and laws that remove '
                           'or mitigate it do',
                'authority': 'Constitution of the Republic of Azerbaijan, article 149(VII); Constitutional Law on '
                             'Normative Legal Acts (No. 21-IVKQ, 21 December 2010), article 87',
                'decided_here': False,
            },
        },
        'citation': {'file': r'((?:constitution|code|law|constitutional-law|referendum-act)/[0-9]+)/madde-0*'
                             r'([0-9]+(?:-[0-9]+)?)\.md',
                     'cites': r'(^|[^0-9.\-]){n}(\.[0-9.]+)?-?(c[ıiuü]|[ıiuü]nc[ıiuü]) madd'},
        'tool': 'tools/in_force_on.py',
    }

    files = {
        'corpus.json': (json.dumps(corpus, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
        'README.md': fill((REPO_FILES / 'README.md').read_text('utf-8')).encode('utf-8'),
        'REPRODUCE.md': fill((REPO_FILES / 'REPRODUCE.md').read_text('utf-8')).encode('utf-8'),
        'LICENSE': (REPO_FILES / 'LICENSE').read_bytes(),
        'laws.csv': laws_csv.encode('utf-8'),
        'data/issues.csv': iss.getvalue().encode('utf-8'),
        'data/stats.json': (json.dumps(stats, indent=1, sort_keys=True) + '\n').encode('utf-8'),
        'data/texts-sha256.tsv': sums.encode('utf-8'),
        'tools/in_force_on.py': (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes(),
    }
    for name in SCRIPTS:
        files[f'tools/build/{name}'] = (HERE / name).read_bytes()
    for name in ('README.md', 'REPRODUCE.md', 'LICENSE', 'tools/in_force_on.py'):
        files[f'tools/build/repo/{name}'] = (REPO_FILES / name).read_bytes()
    _ = author_of
    return files
