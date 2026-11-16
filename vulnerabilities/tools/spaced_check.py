"""Hand-check helper: articles whose heading is letter-spaced ("M a d d ə 40.") or has a note mark right after the number
("Maddə 16[^1]") or before the heading ("[^2]Maddə 9.") and that have no file of their own at the pin: the text sits in
another article's file. By act."""
import re, subprocess
from collections import defaultdict
from pathlib import Path

S = Path(__file__).parent / "gl/vulnerabilities/scripts"
repo = S / "sources/corpus/azerbaijan-law.git"
pin = "6e21fc97acde86122537dca2cfab4abb85c1fb29"
LAW = ("qanun/", "mecelle/", "konstitusiya/", "konstitusiya-qanunu/", "referendum-akti/")
SPACED = re.compile(r"(?m)^M a d d ə\s+(\d+(?:-\d+)?)\s*\.")
MARKED = re.compile(r"(?m)^(?:Maddə\s+(\d+(?:-\d+)?)\[\^\d+\]|\[\^\d+\]Maddə\s+(\d+(?:-\d+)?)\s*\.)")
ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", pin], capture_output=True).stdout.decode("utf-8").splitlines()
items = [(l.split()[2], l.split("\t", 1)[1]) for l in ls if l.split("\t", 1)[1].startswith(LAW)]
have = {p for _, p in items}
p = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=("\n".join(s for s, _ in items) + "\n").encode(),
                   capture_output=True).stdout
pos = 0
res = {"spaced": defaultdict(set), "marked": defaultdict(set)}
for sha, path in items:
    nl = p.index(b"\n", pos); size = int(p[pos:nl].split()[2]); text = p[nl + 1:nl + 1 + size].decode("utf-8", "replace"); pos = nl + 1 + size + 1
    body = text.split("\n[^1]:", 1)[0]
    act = path.rsplit("/", 1)[0]
    for kind, rx in (("spaced", SPACED), ("marked", MARKED)):
        for n in rx.findall(body):
            n = n if isinstance(n, str) else (n[0] or n[1])
            if f"{act}/madde-{n}.md" not in have:
                res[kind][act].add(n)
for kind, acts in res.items():
    print(kind, "acts:", len(acts), "articles without a file:", sum(len(v) for v in acts.values()))
    for a, v in sorted(acts.items(), key=lambda kv: -len(kv[1])):
        print("  ", a, len(v), sorted(v, key=lambda x: [int(y) for y in x.split("-")])[:8])
