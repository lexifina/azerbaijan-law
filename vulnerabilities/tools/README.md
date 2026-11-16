# Tools

The scripts behind this Azerbaijan-only run of global-law's vulnerability detectors. They run inside a copy of
[global-law/vulnerabilities/scripts](https://github.com/lexifina/global-law/tree/main/vulnerabilities/scripts) (Python 3.11+,
`pip install duckdb pyarrow`), with a bare clone of this repository at `sources/corpus/azerbaijan-law.git`, a blobless bare
clone of global-law at `sources/global-law.git`, and a `pins.json` that names only azerbaijan-law, its commit, its language
(`az`) and its code (`AZ`). `build_vulns.py`, `flags_chart.py`, `late_ext_select.py`, `late_ext_rebut.py`, `config.json` and
`patch_az.py` sit three folders up, next to the copy of global-law (`gl/vulnerabilities/scripts/`).

| Script | What it does |
| --- | --- |
| `run.sh` | Applies `patch_az.py`, indexes the history and texts, maps paths to the folders since the move (`map_moved.py`), adds this repository's history rows, and runs the detectors (`bash run.sh <shards>`; run here with 6) |
| `add_root.py` | Builds the history rows from this repository's own commits (global-law replays it only up to an earlier commit), so the history detectors read every change |
| `map_moved.py` | Rewrites the paths in the history table to each act's folder since the move of 10 November 2026 (`data/paths.json`: `code/46944/` to `mecelle/1999/46944/`, `law/5825/` to `qanun/2004/590-IIQ/`), so that an act's history is not split in two at the move; here 6,601 folders and 147,910 paths |
| `run_triage.sh` | The model review: the 40 strongest flags per category, the 40 strongest lapsed time limits in law texts, and the empty periods |
| `late_ext_select.py` | Chooses the empty periods for global-law's review of that category (here the one there is) |
| `late_ext_rebut.py` | Adds the second, arguing-against pass to the empty-period review, as `triage.py` does for the other categories |
| `build_vulns.py` | Builds `data/flags.csv`, `data/reviewed.csv` and `data/by_category.csv` from the findings and the model review |
| `flags_chart.py` | Draws the chart at the top of the READMEs, in Azerbaijani and English, light and dark |
| `config.json` | The repository, the Azerbaijani category names, the files and folders that are not law, and the chart's labels |
| `patch_az.py` | The Azerbaijani fixes below, in the copy of global-law's scripts (`python -X utf8 patch_az.py <scripts dir>`; every fix carries a marker, and a fix already in place is skipped) |
| `patch_detectors.py` | Fixes blind spots found in runs on several country repositories in the copy of global-law's scripts (`python -X utf8 patch_detectors.py <scripts dir>`; a fix already in place is skipped) |
| `patch_detectors_vi.py`, `patch_es.py`, `patch_ca.py`, `patch_en.py`, `patch_de.py`, `patch_en_et.py`, `patch_co.py`, `patch_sv.py`, `patch_pt.py`, `patch_ru.py`, `patch_r18.py`, `patch_xk.py`, `patch_mo.py`, `patch_lu.py`, `patch_li.py`, `patch_mx.py`, `patch_mn.py`, `patch_mt.py`, `patch_np.py`, `patch_en_nr.py` | The same for the Vietnamese, Spanish, Catalan, English, German, Colombian, Salvadoran, Brazilian Portuguese, Russian, Kosovo, Macau, Luxembourg, Liechtenstein, Mexican, Mongolian, Maltese, Nepali and Nauruan blind spots found by other runs, and an eighteenth round found by the Germany run (`patch_r18.py`). None was written for Azerbaijani text. This run's copy carried `patch_detectors.py` (all but two fixes, below), `patch_detectors_vi.py`, `patch_es.py` and `patch_ca.py`; on a fresh copy with every patch here applied in order, `patch_az.py` last, the time limits and amounts read from the Azerbaijani law files are the same as this run's |
| `apply_patches.py` | Applies every patch above once, in order, and records each in the scripts folder (`python -X utf8 apply_patches.py <scripts dir>`); `patch_az.py` is last |
| `redo.py` | Runs those patches through `apply_patches.py`, then again only the scans and detectors the fixes change, the model review of lapsed time limits, references to deleted provisions and empty periods, and the build (`python -X utf8 redo.py <run folder> [--keep-reviews] [--full]`; `--keep-reviews` keeps every review already made and reviews only new strong flags; `--full` runs every step again through `run.sh`; `EMBED_FONTS` names the script that embeds the chart's fonts) |
| `spaced_check.py` | Counts the articles whose heading is letter-spaced ("M a d d ə 40.") or carries a note mark ("Maddə 16[^1]", "[^2]Maddə 9.") and that have no file of their own (the 387 articles in 19 acts and 16 in 8 acts in the READMEs); run from the run folder |
| `toc_check.py` | Finds the acts whose article files hold only headings while one file holds the whole text (the Competition Code, `madde-84.md`); run from the run folder |

The model review needs `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` and `LLM_AUTH` set for an OpenAI-compatible Responses API.
It was run with a regex that marks the root files, `data/` and `tools/` as not law; every law is under `konstitusiya/`,
`referendum-akti/`, `konstitusiya-qanunu/`, `mecelle/` or `qanun/`, so the 40 strongest lapsed time limits in law texts are
the 40 strongest of all. 146 flags were reviewed and 145 still match a flag: the review of a stale amount ("2625-ları", read
as the Georgian lari) was made before the fix for it below, and that flag is gone.

`add_root.py` is the kit's, unchanged: it counted 6,912 commits as law, beside 2,625 baselines. The 1,041 commits `Kind:
several` (a change whose e-qanun notes name more than one act, credited to none and dated by the latest), the 212 `Kind:
unexplained`, the 76 `Kind: repeal` (an act repealed whole) and the 2 documentation commits were left out.

Changes made for this repository, all in `patch_az.py` (in the copy of global-law's scripts; each only for a corpus whose
language is `az`, except where it says otherwise):

- `ingest/textscan.py`, time limits: Azerbaijani writes the date first and "until" as a suffix or a word after it
  ("2020-ci il dekabrın 31-dək", "1997-ci il dekabrın 31-nə qədər", "31 dekabr 2020-ci il tarixinədək", "2020-ci il 1 yanvar
  tarixinə qədər", "2020-ci ilin sonunadək"), and the deadlines "ən geci" and "... tarixdən gec olmayaraq"; none was read.
  They now are (495 time limits in the current law files, where there had been none); a phrase with a year only
  ("2010-cu ilədək") is left out. e-qanun's notes at the end of each file ("[^1]: ... Qanunu ilə ...", which quote the earlier
  wording) are no longer read as the provision's text, for time limits and amounts alike.
- `ingest/textscan.py`, amounts: "100 manatadək" and "manatdan" are manat; and, for every language, a unit with a dotless ı
  is not a currency: the plural ending in "2625-ları" was read as the Georgian lari (Python's case-insensitive match takes
  ı for i).
- `ingest/refscan.py`: "Bu Qanunun 12.3-cü maddəsi" (an article and its part, numbered with a dot) is a reference to
  Article 12; "... Məcəlləsinin 5-ci maddəsi", "... Qanununun 7-ci maddəsi" name another act; "Qanunvericilik Toplusu,
  2004-cü il, № 3, maddə 123" is an entry in the official gazette, not Article 123; e-qanun's notes are not read for
  references.
- `detectors/currency_scan.py`: "lira" (the Turkish lira, in use), "inti" (inside "intizam", "intihar" and "tikinti") and the
  dinar (in use) are not dead currencies in Azerbaijani.
- `detectors/placeholder_ref.py`: it calls `refscan.py`'s `refs()` without setting the language `refs()` reads, so the
  notes and gazette entries above were still read there (and so were the Czech and Slovak rules in `refs()`); it now sets
  it, for every language. This was found after the run, when the two fixes of `patch_detectors.py` this copy did not yet
  carry were applied: the repeal word searched in the whole text and kept only if it starts in the first 70 characters
  (`placeholder_ref.py`), and the Swiss franc, the sucre and the zaire (`currency_scan.py`). With the first alone, the
  search for references to repealed placeholders raised 7 flags, all gazette entries or notes, where it had raised 1 (a
  note); with the language set too, none. `placeholder_ref.py` and `currency_scan.py` were then run again and the build
  redone; the dead currencies did not change.
- `run.sh` runs `patch_az.py` before the scans. In `apply_patches.py` it is last: its fixes edit lines that `patch_ca.py`
  (the deadline words) and `patch_mn.py` (the dates) look for, and it finds its own place after them.
