# Azerbaijani law, change by change

The national legislation of the Republic of Azerbaijan as a git repository: the Constitution, {{REFERENDUM_ACTS}} referendum acts that amended it, {{CONSTITUTIONAL_LAWS}} constitutional laws, {{CODES}} codes and {{LAWS_ORDINARY}} laws, in force and repealed, from [e-qanun.az](https://e-qanun.az), the Unified Internet Electronic Database of Legal Acts of the Ministry of Justice. Each article is its own file, with one paragraph per line. Every change is a commit credited to the act that made it and dated the day it took effect, at noon Baku time. The text is the Azerbaijani original, the authoritative text.

On `main`, the record runs from {{FIRST}} to {{LAST}} in {{COMMITS}} commits, built from {{TEXTS}} texts: each act's current text plus every dated edition e-qanun keeps of it. A further {{FUTURE_COMMITS}} commits take effect after the build day ({{TODAY}}) and sit on the `future` branch.

## A lawyer's questions as git commands

| Question | Command |
| --- | --- |
| What did article 1 of the Law on Public Procurement say on 1 January 2022? | `python tools/in_force_on.py 2022-01-01 law/1029 1` |
| The whole Civil Code on a date | `python tools/in_force_on.py 2024-06-01 code/46944` |
| Which act last changed each paragraph of an article? | `git blame code/46944/madde-107.md` |
| Every change to an article, with the act behind it | `git log -p code/46944/madde-107.md` |
| The words that changed, not whole paragraphs | `git log -p --word-diff code/46944/madde-107.md` |
| Everything one act changed, across every law | `git log --author='452-VIIQD' --stat` |
| Every act that changed a law, in order | `git log --format='%(trailers:key=In-force,valueonly,separator=) %an' -- code/46944` |
| What takes effect after today | `git log main..future` |
| The list of acts, with their e-qanun links | [`laws.csv`](laws.csv) |

Use `tools/in_force_on.py` for "on this date" questions rather than `git log --before`. It picks the text by the `In-force:` trailer, so it is right in any time zone. If you use raw git, write the time out in full: `git rev-list -1 --before="2022-01-01T23:59:59+04:00" main`. In PowerShell, `git show "$(git rev-list -1 --before=... main):law/1029/madde-1.md"` needs the quotes. Pass `-c core.quotepath=false` to git when scanning paths.

Folders are `constitution/`, `referendum-act/`, `constitutional-law/`, `code/` and `law/`, and each act's folder is named after its e-qanun number, the `N` in `e-qanun.az/framework/N`. Inside it there is one file per article (`madde-4.md`, `madde-13-1.md`; an article numbered with a superscript, such as 98¹ in the Constitution, becomes `madde-98-1.md`, the form the acts use when they cite it: "98-1-ci maddə"), and `title.md` for the text before the first article. Headings of parts and chapters stay at the end of the article before them. An act without articles is all in `title.md`.

Each file ends with e-qanun's notes on that article, renumbered `[^1]`, `[^2]` ... per file, with the note's mark kept where e-qanun prints it. A note names the act that made a change and often quotes the earlier wording ("Əvvəlki redaksiyada deyilirdi: ..."). The official-publication reference inside each note ("“Azərbaycan” qəzeti, ..., Qanunvericilik Toplusu, ...") is removed, because e-qanun fills it in over the months after a change; the act's publication date is in the commit's `Published:` trailer.

## The dates, and which one we use

**Commits are dated by the day the change took effect**: e-qanun's in-force date for the act that made it ("Qüvvəyə minmə tarixi"). Where e-qanun gives none ({{IN_FORCE_FROM_PUBLICATION}} acts, mostly before 2005), the act's first official publication is used, since laws take effect on the day of their official publication unless they set a later date (Constitutional Law on Normative Legal Acts, No. 21-IVKQ, article 85.1: `constitutional-law/21300/madde-85.md`); the `In-force-basis:` trailer says which. The adoption date is in `Adopted:`, the first publication in `Published:`.

An act often takes effect later than it is published. e-qanun then either prints its change at once, or prints only a starred note ("* (... 451-VIIQD nömrəli Qanunu ilə 107.4-cü maddənin dördüncü cümləsinə edilmiş dəyişiklik 2027-ci il yanvarın 24-dən qüvvəyə minir.)") and applies the words later. Either way, a change credited to an act is committed on the act's in-force date, so `main` does not show it early; a starred note that arrives on its own goes with the change it was printed with. Where one act takes effect in stages, the whole of its change is on its main in-force date, and the starred notes give the later dates.

**Changes that take effect after the build day** are on the branch `future`, which starts at the tip of `main` and is never merged into it. After a rebuild, run `git fetch --force origin future`.

## What "author" means

The author of a commit is the act that made the change, at an address that cannot exist, for example `Qanun 452-VIIQD (14.07.2026) <452-viiqd-20260714-62294@e-qanun.invalid>`. The number is the act's official number (QD: a law amending others; Q: a law; KQ: a constitutional law) and the date its adoption date. So `git blame` names, for each paragraph, the act that last wrote it. One commit holds everything one act changed on one day, across every law it touched, together with the act's own text when it took effect.

e-qanun's dated editions do not say which act each edition is for. The builder reads the notes instead: a changed article whose notes newly name one act is credited to that act (`Evidence: e-qanun note`, {{EVIDENCE_NOTE}} changes). Where an article's notes newly name several acts, each changed block of lines goes to the one act named by the note marks on those lines, and the article is written step by step in the acts' order (`Evidence: e-qanun note on the changed lines`, {{EVIDENCE_LINES}}). A changed article whose notes name no new act goes to the one act newly named anywhere in that edition, if there is exactly one (`Evidence: e-qanun edition`, {{EVIDENCE_EDITION}}). What remains is labelled and credited to no act; it is authored by `e-qanun.az (Ministry of Justice of Azerbaijan)`:

- `Kind: several` ({{C_SEVERAL}} commits): lines changed between two editions whose note marks name several acts (or none, while the article's notes name several). Each act is listed in a `Candidate:` trailer, and the commit is dated by the latest of them. Most are in the codes, whose first kept text after the original is from 2021: the wording in between is not in the source, so a paragraph changed several times from 2000 to 2021 shows one labelled change.
- `Kind: unexplained` ({{C_UNEXPLAINED}} commits): the article changed but no note names an act (often e-qanun correcting its own text). Dated by the e-qanun edition.
- `Kind: baseline` ({{C_BASELINE}} commits): see below.

Blame credits whole paragraphs. A paragraph changed by two acts names only the later one, so use `git log -p --word-diff` to see each act's words.

## What it does not show

- **Wording older than e-qanun's first kept text.** e-qanun keeps dated editions mostly from 2021, and the act as adopted for {{WITH_ORIGINAL}} of the {{ACTS}} acts. For the rest, the first text is a later consolidation. Its articles that carry no amendment note are the act's original text and are dated by the act's own in-force date. Articles that do carry notes were changed before that consolidation, and their earlier wording is not in the source (the notes often quote it). They appear only from the in-force date of the latest act their notes name, in a `Kind: baseline` commit that lists those acts as `Candidate:`. So for an early date, such an article is missing rather than wrong. This applies to the Constitution: its 2002, 2009 and 2016 amendments are each a baseline commit for the articles they touched, dated by the referendum act.
- Sub-laws: presidential decrees and orders, Cabinet decisions and ministerial acts. They are not in this build.
- Texts e-qanun could not serve or we could not read ({{ISSUES}} issues, in [`data/issues.csv`](data/issues.csv)).
- e-qanun's links, images and its Russian and English translations.
- Renumbering: an article that moves to a new number appears as one file removed and another added.

This repository is a research aid and is not an official publication. For the authoritative text, see the act at the `Source:` link.

## How it is checked

- The text at the tip of `future` (or `main`) equals e-qanun's current text of every act, file for file, and repealed acts are gone.
- Every word of each source text is in the files built from it (`tools/build/check_repo.py`).
- `tools/in_force_on.py` was compared with e-qanun's own dated editions for several articles and dates.
- Every commit's trailers parse with `git interpret-trailers --parse`; `main` has no merge commits, its commit dates never go backwards, and none is after the build day.
- Two builds from the same cache give the same commit hashes.

The sha256 of every downloaded text is in [`data/texts-sha256.tsv`](data/texts-sha256.tsv). See [`REPRODUCE.md`](REPRODUCE.md).

## How it is built

`tools/build/fetch.py` lists every act of the five kinds through e-qanun's open JSON API (api.e-qanun.az), reads each act's requisites, dated editions and related acts, and downloads every text. `parse_text.py` splits each text into articles, paragraphs and notes. `build.py` compares each act's texts in order, credits each change as above, and writes the whole history with one `git fast-import`. No AI model reads or writes any text, either in the build or in the checks.

## Licence

Source: e-qanun.az, Unified Internet Electronic Database of Legal Acts, Ministry of Justice of the Republic of Azerbaijan. Under article 7(a) of the Law of the Republic of Azerbaijan on Copyright and Related Rights (No. 115-IQ, 5 June 1996; `law/4167/madde-7.md`), official documents (laws, court decisions and other texts of a legislative, administrative or judicial nature) and their official translations are not objects of copyright. e-qanun publishes no terms of use; its footer reads "Bütün Haqqlar Qorunur" (all rights reserved), which can only cover the site itself. Reuse is therefore believed to be free but is not stated by the publisher, and the repository stays private. The texts here were split into files and arranged as commits; their wording was not changed, except that note references were renumbered per file and the publication references inside notes removed. Lexifina's own contributions (the tools, the arrangement and the commit messages) are CC0. See [`LICENSE`](LICENSE).
