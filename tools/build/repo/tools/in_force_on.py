"""Print an Azerbaijani act, or one article of it, as it stood on a date.

    python tools/in_force_on.py 2024-06-01 code/46944           # every file of the Civil Code on that day
    python tools/in_force_on.py 2024-06-01 code/46944 107       # article 107 (file madde-107.md)
    python tools/in_force_on.py 2024-06-01 constitution/897 98-1   # article 98-1 (98 with superscript 1)

Reads the `In-force:` trailers (the real dates; commit dates before 1970 are clamped), so it is right for any day,
in any time zone. Only `main` is read: texts that apply after the build day are on the `future` branch.
Either folder name works: the one in data/paths.json (kind/year/number) or the older one it maps from.
Standard library only.
"""
import json
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', '-c', 'core.quotepath=off', *args], capture_output=True, text=True, encoding='utf-8',
                          check=True).stdout


def commit_on(day: str, path: str) -> str | None:
    """The last commit on or before `day` that touched `path`."""
    fmt = '%H%x1f%(trailers:key=In-force,valueonly,separator=)%x1f%(trailers:key=Consolidated,valueonly,separator=)'
    best = None
    for line in git('log', '--first-parent', f'--format={fmt}', 'main', '--', path).splitlines():
        h, inforce, consolidated = (line.split('\x1f') + ['', ''])[:3]
        d = (inforce or consolidated).strip()
        if d and d <= day:
            best = h
            break
    return best


def names_of(law: str, ref: str) -> list[str]:
    """`law` and its other folder name across the layout move (data/paths.json maps each old folder to its folder):
    the folder it has now first, then its old name, so either name reads every day of its history."""
    try:
        paths = json.loads(git('show', f'{ref}:data/paths.json')).get('paths', {})
    except (subprocess.CalledProcessError, ValueError):
        return [law]
    if law in paths:
        return [paths[law], law] if paths[law] != law else [law]
    return [law, *[o for o, n in paths.items() if n == law and o != law]]


def resolve(day: str, law: str, ref: str, path_of, commit_of):
    """(folder, path, commit) for the name the law had on `day`: the first name whose text exists then."""
    first = None
    for name in names_of(law, ref):
        p = path_of(name)
        h = commit_of(p)
        if first is None:
            first = (name, p, h)
        if h and git('ls-tree', '--name-only', h, p).strip():
            return name, p, h
    return first


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    day, law = sys.argv[1], sys.argv[2].strip('/')
    unit = sys.argv[3] if len(sys.argv) > 3 else None
    law, path, h = resolve(day, law, 'main',
                           lambda n: f'{n}/madde-{unit}.md' if unit and unit != 'title' else (f'{n}/title.md' if unit else n),
                           lambda p: commit_on(day, p))
    if not h:
        sys.exit(f'{path}: no text on or before {day} (the law was not yet in force, or the file did not exist then)')
    if unit:
        if not git('ls-tree', '--name-only', h, path).strip():
            sys.exit(f'{path}: not in the text in force on {day} (removed by the commit {h[:10]})')
        sys.stdout.write(git('show', f'{h}:{path}'))
        return
    names = git('ls-tree', '-r', '--name-only', h, f'{law}/').splitlines()
    names = [n for n in names if n.endswith('.md')]
    def order(n: str):
        stem = n.rsplit('/', 1)[-1][:-3]
        num = stem[6:] if stem.startswith('madde-') else ''
        parts = [int(x) if x.isdigit() else 0 for x in num.replace('-', '.').split('.')] if num else []
        return (n.rsplit('/', 1)[0], stem != 'title', not num, parts, stem)
    for n in sorted(names, key=order):
        sys.stdout.write(git('show', f'{h}:{n}') + '\n')


if __name__ == '__main__':
    main()
