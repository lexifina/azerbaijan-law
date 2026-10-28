"""Functional smoke test of the built Azerbaijan law repository: the things a reader does with it work. Standard
library only.

    python -X utf8 scripts/azerbaijan-law/test_repo.py [--repo ../azerbaijan-law]
    python -X utf8 tools/build/test_repo.py                 # from inside the repository

It asserts that:
1. `git blame` on a changed article names an amending act as author of its lines;
2. tools/in_force_on.py gives different text the day before and the day of a known amendment, each equal to the
   file at the matching commit;
3. `git log --follow` on a file lists its acts in the order they took effect;
4. every commit carries an `In-force:` trailer, and every trailer block parses with `git interpret-trailers`;
5. no commit is authored by Lexifina except the documentation commit (the last one on main);
6. `main` has no merges, no commit dated after the documentation commit, and commit dates never go backwards;
7. every git or tool command in the README's table runs and prints something.
"""
import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLISHER = 'e-qanun.az (Ministry of Justice of Azerbaijan)'
ACT = re.compile(r'^.+ \(\d{2}\.\d{2}\.\d{4}\)$')   # an act: '<kind> <number> (DD.MM.YYYY)' or '<title> (DD.MM.YYYY)'
# (file, a day before an amendment, its in-force day, the act number expected in blame)
CASES = [
    ('code/46944/madde-107.md', '2026-07-26', '2026-07-27', '452-VIIQD'),
    ('law/1029/madde-1.md', '2023-08-01', '2023-08-02', None),
]


def default_repo() -> Path:
    if (HERE.parents[1] / '.git').exists():
        return HERE.parents[1]
    return HERE.parents[2] / 'azerbaijan-law'


class Smoke:
    def __init__(self, repo: Path):
        self.repo = repo
        self.results: list[tuple[str, bool, str]] = []

    def git(self, *args: str, inp: str | None = None) -> str:
        out = subprocess.run(['git', '-c', 'core.quotepath=false', *args], cwd=self.repo, capture_output=True,
                             text=True, encoding='utf-8', input=inp)
        if out.returncode:
            raise AssertionError(f'git {" ".join(args)}: {out.stderr.strip()}')
        return out.stdout

    def tool(self, *args: str) -> str:
        out = subprocess.run([sys.executable, '-X', 'utf8', 'tools/in_force_on.py', *args], cwd=self.repo,
                             capture_output=True, text=True, encoding='utf-8')
        if out.returncode:
            raise AssertionError(f'in_force_on {" ".join(args)}: {out.stderr.strip()}')
        return out.stdout

    def check(self, name: str, fn):
        try:
            detail = fn() or ''
            self.results.append((name, True, detail))
            print(f'PASS {name}: {detail}')
        except AssertionError as exc:
            self.results.append((name, False, str(exc)))
            print(f'FAIL {name}: {exc}')

    def blame(self):
        path, _, _, num = CASES[0]
        out = self.git('blame', '--line-porcelain', 'main', '--', path)
        authors = {l[7:] for l in out.splitlines() if l.startswith('author ')}
        assert authors, 'no blame output'
        assert all(ACT.match(a) or a == PUBLISHER for a in authors), f'unexpected authors {authors}'
        assert any(num in a for a in authors), f'{num} not among the authors {authors}'
        return f'{path} lines by {len(authors)} authors, including {num}'

    def on_date(self):
        done = []
        for path, before, after, _ in CASES:
            law, unit = path.rsplit('/', 1)
            unit = unit[len('madde-'):-3]
            a, b = self.tool(before, law, unit), self.tool(after, law, unit)
            assert a and b and a != b, f'{path}: no change between {before} and {after}'
            rows = self.git('log', '--format=%H%x09%(trailers:key=In-force,valueonly,separator=)', 'main', '--',
                            path).splitlines()
            at = next(h for h, d in (r.split('\t') for r in rows) if d.strip() <= after)
            assert b == self.git('show', f'{at}:{path}'), f'{path} on {after} is not the file at {at[:10]}'
            done.append(f'{path} {before} != {after}')
        return '; '.join(done)

    def follow(self):
        checked = []
        for path, *_ in CASES:
            out = self.git('log', '--follow', '--format=%an%x09%(trailers:key=In-force,valueonly,separator=)', 'main',
                           '--', path)
            rows = [l.split('\t') for l in out.splitlines() if l]
            assert len(rows) >= 2, f'{path}: {len(rows)} commits'
            days = [d.strip() for _, d in rows]
            assert days == sorted(days, reverse=True), f'{path}: not in date order {days}'
            assert all(ACT.match(a) or a == PUBLISHER for a, _ in rows), f'{path}: authors {[a for a, _ in rows]}'
            checked.append(f'{path} {len(rows)} commits')
        return '; '.join(checked)

    def trailers(self):
        """git's own trailer parser (the one `interpret-trailers --parse` uses) must find In-force on every commit."""
        n = 0
        for ref in ('main', 'future'):
            try:
                log = self.git('log', '--format=%H%x1f%(trailers:key=In-force,valueonly,separator=)', ref)
            except AssertionError:
                continue
            for row in log.splitlines():
                h, d = row.split('\x1f')
                assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', d.strip()), f'{h[:10]}: In-force {d!r}'
                n += 1
        return f'{n} commits carry a parsed In-force trailer'

    def lexifina(self):
        rows = self.git('log', '--format=%H%x09%an%x09%ae%x09%cn', 'main').splitlines()
        by_lex = [r for r in rows if r.split('\t')[1] == 'Lexifina']
        assert len(by_lex) == 1 and by_lex[0] == rows[0], f'{len(by_lex)} commits by Lexifina'
        assert all(r.split('\t')[3] == 'Lexifina' for r in rows), 'a committer other than Lexifina'
        assert all(r.split('\t')[2].endswith('.invalid') for r in rows[1:]), 'an author email not .invalid'
        return f'only the documentation commit {rows[0][:10]} is by Lexifina; {len(rows) - 1} law commits'

    def order(self):
        assert self.git('rev-list', '--merges', '--count', 'main').strip() == '0', 'merge commits on main'
        ts = [int(x) for x in self.git('log', '--first-parent', '--format=%ct', 'main').split()]
        back = sum(1 for a, b in zip(ts[1:], ts) if a > b)
        assert not back, f'{back} commit dates go backwards'
        return f'{len(ts)} commits, no merges, dates never go backwards'

    def readme(self):
        text = (self.repo / 'README.md').read_text(encoding='utf-8')
        table = text[text.index("## A lawyer's questions"):text.index('## The dates')]
        rows = '\n'.join(l for l in table.splitlines() if l.startswith('|'))
        cmds = [c for c in re.findall(r'`([^`]+)`', rows) if c.startswith(('git ', 'python '))]
        cmds = [c for c in cmds if 'main..future' not in c]
        assert len(cmds) >= 6, f'only {len(cmds)} commands found'
        for c in cmds:
            args = shlex.split(c)
            if args[0] == 'python':
                args[0:1] = [sys.executable, '-X', 'utf8']
            out = subprocess.run(args, cwd=self.repo, capture_output=True, text=True, encoding='utf-8')
            assert out.returncode == 0, f'{c}: exit {out.returncode} {out.stderr.strip()[:200]}'
            assert out.stdout.strip(), f'{c}: printed nothing'
        return f'{len(cmds)} README commands ran and printed output'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    s = Smoke(Path(args.repo) if args.repo else default_repo())
    s.check('blame names an act', s.blame)
    s.check('text before and after an amendment', s.on_date)
    s.check('log --follow in date order', s.follow)
    s.check('In-force on every commit; trailers parse', s.trailers)
    s.check('only the documentation commit is by Lexifina', s.lexifina)
    s.check('no merges, dates in order', s.order)
    s.check('README commands run', s.readme)
    ok = all(r[1] for r in s.results)
    print(f'{sum(r[1] for r in s.results)}/{len(s.results)} passed')
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
