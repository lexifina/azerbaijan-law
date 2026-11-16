"""Hand-check helper: acts at the pin whose article files hold only their heading (one line, perhaps a chapter heading),
while one article file holds the act's whole text, its articles' headings again among it (e-qanun's table of contents
read as the articles); by act, with the file that holds the text and its size."""
import re, subprocess
from collections import defaultdict
from pathlib import Path

S = Path(__file__).parent / "gl/vulnerabilities/scripts"
repo = S / "sources/corpus/azerbaijan-law.git"
pin = "6e21fc97acde86122537dca2cfab4abb85c1fb29"
LAW = ("qanun/", "mecelle/", "konstitusiya/", "konstitusiya-qanunu/", "referendum-akti/")
ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-l", pin], capture_output=True).stdout.decode("utf-8").splitlines()
acts = defaultdict(list)
for l in ls:
    meta, path = l.split("\t", 1)
    if path.startswith(LAW) and "/madde-" in path:
        acts[path.rsplit("/", 1)[0]].append((path, meta.split()[2], int(meta.split()[3])))
items = [x for v in acts.values() for x in v]
p = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=("\n".join(s for _, s, _ in items) + "\n").encode(),
                   capture_output=True).stdout
text, pos = {}, 0
for path, sha, _ in items:
    nl = p.index(b"\n", pos); size = int(p[pos:nl].split()[2]); text[path] = p[nl + 1:nl + 1 + size].decode("utf-8", "replace"); pos = nl + 1 + size + 1
HEAD = re.compile(r"(?m)^(?:Maddə|M\s?a\s?d\s?d\s?ə)\s+(\d+(?:-\d+)?)\s*[.:]")
out = []
for act, files in acts.items():
    if len(files) < 4:
        continue
    bodies = {f: text[f].split("\n[^1]:", 1)[0] for f, _, _ in files}
    bare = [f for f in bodies if len([x for x in bodies[f].splitlines() if x.strip()]) <= 3 and len(bodies[f]) < 400]
    if len(bare) < 0.5 * len(files):
        continue
    big = max(files, key=lambda x: x[2])
    own = big[0].rsplit("/madde-", 1)[1][:-3]
    heads = set(HEAD.findall(bodies[big[0]])) - {own}
    if len(heads) >= 0.5 * len(files):
        out.append((act, len(files), len(bare), big[0].rsplit("/", 1)[1], big[2], len(heads), text[act.rsplit("/", 1)[0] and big[0]].splitlines()[0][:60]))
print("acts whose article files hold only headings, the text in one file:", len(out))
for o in sorted(out, key=lambda o: -o[4]):
    print(*o, sep=" | ")
