# Reproducing this repository

Everything in this history comes from e-qanun.az and can be rebuilt from it. The same downloaded texts give the same commit hashes.

## What this build used

- Retrieved on {{TODAY}}: {{ACTS}} acts ({{CONSTITUTIONS}} constitution, {{REFERENDUM_ACTS}} referendum acts, {{CONSTITUTIONAL_LAWS}} constitutional laws, {{CODES}} codes, {{LAWS_ORDINARY}} laws; {{REPEALED}} of them repealed) and {{TEXTS}} texts (current texts plus dated editions).
- Requests: 13 catalogue pages (`getDetailSearch`), 2 per act for requisites and editions (`framework/<id>`, `getVersions?id=<id>`), 1 per repealed act for related acts (`getRelatedFrw`), and 1 per text.
- {{COMMITS}} commits on `main` ({{C_ORIGINAL}} with an act's own text, {{C_AMENDMENT}} amendment, {{C_REPEAL}} repeal, {{C_BASELINE}} baseline, {{C_SEVERAL}} several, {{C_UNEXPLAINED}} unexplained, and this documentation commit). A further {{FUTURE_COMMITS}} are on `future`.
- The sha256 of every downloaded text (the HTML as served) is in `data/texts-sha256.tsv`; the sha256 of that list is {{TEXTS_SHA256}}.
- Build scripts, copied to `tools/build/`, with their sha256:
  - `eqanun.py` {{SHA_EQANUN_PY}}
  - `fetch.py` {{SHA_FETCH_PY}}
  - `parse_text.py` {{SHA_PARSE_TEXT_PY}}
  - `build.py` {{SHA_BUILD_PY}}
  - `docs.py` {{SHA_DOCS_PY}}
- Tools: Python {{V_PYTHON}} (standard library only); {{V_GIT}}.

## Fetch rate and terms

Neither e-qanun.az nor api.e-qanun.az has a robots.txt (both answer 404, checked {{TODAY}}), so there is no Crawl-delay and no rule for AI agents. The site has no terms-of-use page; its footer says "Bütün Haqqlar Qorunur" (all rights reserved). The JSON API needs no key. The text host answers 403 without a `Referer` header, so the fetcher sends the site's address, as a browser does. All requests used at most 4 parallel connections and asked for gzip (the API and text hosts did not compress). The text host serves about 130 KB/s per connection, so the largest codes took about a minute per edition.

## Steps

```sh
cd tools/build
python fetch.py catalogue      # .cache/catalogue.json: types 27, 28, 30, 107 (and the Constitution, id 897)
python fetch.py meta           # .cache/meta/<id>.json.gz, .cache/versions/<id>.json.gz
python fetch.py related        # .cache/related/<id>.json.gz, for repealed acts
python fetch.py pack           # .cache/index.json.gz: the three above in one file
python fetch.py html           # .cache/html/frameworks/.../f_<id>.html.gz and versions/.../v_<id>_<n>.html.gz
python build.py ../../../azerbaijan-law-rebuilt --today {{TODAY}}
python check_repo.py ../../../azerbaijan-law-rebuilt
```

`--today` is the cache's retrieval day. It is required: it dates the documentation commit and divides `main` from `future`, so a rebuild never depends on the day it is run. The builder refuses to build into a directory that holds anything except an earlier build, and keeps the `origin` remote on a rebuild.

e-qanun adds editions as laws change, so a later fetch gives a longer history. To rebuild this exact history, use texts whose sha256 match `data/texts-sha256.tsv`.

## Decisions

- **Which acts:** every act of e-qanun's types 27 (referendum acts), 28 (constitutional laws), 30 (laws) and 107 (codes), in force or repealed, plus the 1995 Constitution (id 897). The Soviet-era constitutions in type 26 and sub-laws are left out.
- **Which texts:** the current text (`htmlUrl` of `framework/<id>`) and every edition in `getVersions` whose file is `v_<id>_<n>.html` or `c_<n>.html`, in that order (c_ first, then v_ by n). The editions list also has an entry for the current file (`f_<id>.html`) dated by the act's adoption; it is the current text, not the original, and is used once, last. An act's first text is its original when it is `c_<n>` or `v_<id>_1`.
- **Dates:** the act's `effectDate`; where empty, its first "Dərc olunma tarixi" (publication date); where that is empty too, its `acceptDate`. Noon at +0400. Changes dated after `--today` go on `future`. Changes dated before the changed act itself took effect are moved to that day (`In-force-act:` keeps the act's own date).
- **Crediting:** see the README. A note's act is the first "D month YYYY-ci il [tarixli] N nömrəli" (or "YYYY-ci il D month") in each paragraph of the note, up to "deyilirdi" (where the quoted earlier wording starts). Numbers are matched to e-qanun's act numbers, preferring the act adopted on the note's date. The Constitution's notes name the Central Election Commission decisions that confirmed each referendum; they are credited to the referendum act of that year. A note naming an act that is not in the list of laws (a presidential decree, a court decision) is dated by its adoption date (`In-force-basis:` says so).
- **Repeal:** a repealed act's files are deleted on the in-force date of the act e-qanun lists as repealing it ("Ləğv edilib"). Repealed acts for which e-qanun names no repealing act are listed in `data/issues.csv` and stay in the tree.
- **Units:** an article starts at a paragraph that begins "Maddə N." outside quoted text. Each paragraph, list item or table row (cells joined by " | ") is one line. Endnote marks become `[^k]`, numbered per file, and the notes follow the text.
- **Normalised away:** runs of whitespace inside a line (collapsed to one space), soft hyphens and zero-width characters, and the publication references inside notes. Any other difference between two texts, including a space added between two words, is a change.
- **Order:** by in-force date. A change printed in an earlier edition but taking effect after a change printed in a later one is re-applied by a three-way line merge onto the text then in force, or, where that fails, held back to the later commit (`Held-back:` / `Includes-held-back:`).

## What AI did

This repository was built by Claude Code with Claude Opus 5.5 (`claude-opus-5-5`), which wrote the scripts and this documentation. No AI model reads, writes, summarises or classifies any legal text, either at data-build time or at git-build time. Commit messages are generated by code from e-qanun's metadata.

## Verification (2026-10-28)

- `check_repo.py`: the final text of all 7,240 acts equals e-qanun's current text (0 differ); the words of all 7,887 source texts, read independently from the raw HTML, equal the built files (0 differ).
- Two builds from the same cache gave identical `main` and `future` hashes (610177c / 7856df0, before the documentation commit carried this section and the final test_repo.py; the law commits before the documentation commit are unchanged since).
- `test_repo.py` 7/7; `scripts/test_corpus.py` OK; `scripts/global-law/check_corpus.py` pass.
- `tools/in_force_on.py` against e-qanun's dated editions, the day before and the day of each change: law/1029 articles 1 and 10, code/46944 article 107: 6/6 equal.
