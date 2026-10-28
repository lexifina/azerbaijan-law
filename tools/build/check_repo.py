"""Check the Azerbaijan law repository against the e-qanun cache.

    python check_repo.py <repo> [--workers 8]

1. Final text: for every act, the files at the tip of `future` (or `main` when there is no future) equal the files
   parsed from e-qanun's current text, byte for byte; a repealed act whose repealing act is known has no files.
2. Words: for every text in the cache (current texts and dated editions), the words of its body, read crudely from
   the HTML (tags stripped, endnote marks dropped), equal the words of the article and title lines built from it, in
   order. Superscript digits are compared as digits, and the " | " and " / " joins of table cells are ignored.
Prints the mismatches and exits non-zero if there are any.
"""
import argparse
import html as htmlmod
import json
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import parse_text  # noqa: E402

SUPS = str.maketrans(parse_text.SUP_BACK)


def tree(repo: Path, ref: str) -> dict[str, str]:
    ls = subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(repo), 'ls-tree', '-r', ref],
                        capture_output=True, text=True, encoding='utf-8', check=True).stdout
    entries = []
    for line in ls.splitlines():
        meta, path = line.split('\t', 1)
        entries.append((meta.split()[2], path))
    p = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE)
    out = {}
    for sha, path in entries:
        p.stdin.write(sha.encode() + b'\n')
        p.stdin.flush()
        head = p.stdout.readline().split()
        data = p.stdout.read(int(head[2]))
        p.stdout.read(1)
        out[path] = data.decode('utf-8')
    p.stdin.close()
    p.wait()
    return out


def crude_words(raw: bytes) -> list[str]:
    t = parse_text.decode(raw)
    i = t.lower().find('<body')
    t = t[i if i >= 0 else 0:]
    for marker in ("mso-element:endnote-list", "mso-element:footnote-list"):
        j = t.find(marker)
        if j >= 0:
            t = t[:t.rfind('<', 0, j)]
    t = re.sub(r'(?is)<a\b[^>]*href="#_(?:edn|ftn)\d+"[^>]*>.*?</a>', ' ', t)
    t = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', t)
    t = re.sub(r'(?i)<(p|br|div|tr|td|th|li|h\d|table)\b', r' <\1', t)
    t = re.sub(r'(?i)</(p|div|tr|td|th|li|h\d|table)>', ' ', t)
    t = re.sub(r'(?s)<!--.*?-->', ' ', t)          # conditional comments: VML text boxes, Word field codes
    t = re.sub(r'(?is)<span[^>]*display:\s*none[^>]*>[^<]*</span>', '', t)   # hidden text
    t = re.sub(r'<[^>]*>', '', t)
    t = htmlmod.unescape(t)
    t = parse_text.JUNK.sub('', t)
    return norm_words(t)


def norm_words(t: str) -> list[str]:
    t = t.translate(SUPS)
    return [w for w in parse_text.SPACE.split(t) if w and w not in ('|', '/')]


def file_words(files: dict[str, str]) -> list[str]:
    def order(p):
        stem = p.rsplit('/', 1)[-1][:-3]
        return (0,) if stem == 'title' else (1,)
    out = []
    # Title first, then articles in the order the parser found them (the dict keeps insertion order).
    for p in sorted(files, key=order):
        body = files[p].split('\n\n[^1]: ')[0]
        body = re.sub(r'\[\^\d+\]', ' ', body)
        out += norm_words(body)
    return out


def check_words(path: str) -> tuple[str, str | None]:
    raw = build.html_raw(path)
    rec = build.load_parsed(path)
    if raw is None or rec.get('error'):
        return path, None
    a, b = crude_words(raw), file_words(rec['files'])
    if a == b:
        return path, None
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return path, f'words differ at {i}: source {a[max(0, i - 5):i + 6]} built {b[max(0, i - 5):i + 6]} ' \
                 f'(lengths {len(a)} / {len(b)})'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('repo', type=Path)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--skip-words', action='store_true')
    args = ap.parse_args()
    acts = build.load_acts()
    refs = subprocess.run(['git', '-C', str(args.repo), 'branch', '--format=%(refname:short)'], capture_output=True,
                          text=True).stdout.split()
    final = tree(args.repo, 'future' if 'future' in refs else 'main')
    by_dir = defaultdict(dict)
    for p, t in final.items():
        parts = p.split('/')
        if len(parts) == 3 and parts[1].isdigit():
            by_dir[f'{parts[0]}/{parts[1]}'][p] = t
    bad = 0
    ws = 0
    for a in acts:
        d = f"{a['kind']}/{a['id']}"
        have = by_dir.get(d, {})
        if not a['editions'] or (a['status'] != build.INFORCE and not a.get('repealed_by')):
            continue          # left out by the builder (see data/issues.csv)
        rec = build.load_parsed(a['editions'][-1]['path'])
        if rec.get('error'):
            continue
        want = {f'{d}/{k}': v for k, v in rec['files'].items()}
        if a['status'] != build.INFORCE and a.get('repealed_by'):
            want = {}
        if have != want:
            if {p: build.squash(t) for p, t in have.items()} == {p: build.squash(t) for p, t in want.items()}:
                ws += 1
                continue
            bad += 1
            if bad <= 15:
                diff = sorted(set(have) ^ set(want)) or [p for p in want if have.get(p) != want[p]]
                print(f'final text differs: {d}: {diff[:4]}')
    print(f'final text: {len(acts)} acts, {bad} differ, {ws} differ only in whitespace', flush=True)
    wbad = 0
    if not args.skip_words:
        paths = sorted({e['path'] for a in acts for e in a['editions']
                        if a['status'] == build.INFORCE or a.get('repealed_by')})
        with ProcessPoolExecutor(args.workers) as pool:
            for path, err in pool.map(check_words, paths, chunksize=8):
                if err:
                    wbad += 1
                    if wbad <= 15:
                        print(f'{path}: {err}')
        print(f'words: {len(paths)} texts, {wbad} differ', flush=True)
    sys.exit(1 if bad or wbad else 0)


if __name__ == '__main__':
    main()
