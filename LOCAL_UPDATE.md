# Local DBLP Update

This fork is published as a static GitHub Pages site at https://wlcosta.github.io/CSIndex/. DBLP updates are run locally, then the generated static files are reviewed, committed, and pushed.

## Environment

Create and activate the virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Windows, run the repository update scripts from Git Bash or WSL, not PowerShell. Set the interpreter explicitly when running scripts manually:

```bash
export PYTHON="$PWD/.venv/Scripts/python.exe"
```

## Connectivity Test

Before a full update, test one DBLP PID from `data/all-researchers.csv`:

```bash
cd data
"$PYTHON" ../dblp.py -test
```

For a single non-destructive test, request `https://dblp.org/pid/<PID>.xml` and confirm it is XML and can be parsed by `xmltodict`.

## Full Update

From the repository root, after committing or stashing unrelated changes:

```bash
./local_update.sh
```

The official workflow is:

```bash
cd data
PYTHON="$PWD/../.venv/Scripts/python.exe" ./rundblp
PYTHON="$PWD/../.venv/Scripts/python.exe" ./runall
PYTHON="$PWD/../.venv/Scripts/python.exe" ../dblp.py -test
```

The DBLP downloader sleeps about five seconds for each uncached researcher. With 1,300 researchers, a fully uncached update takes at least about 108 minutes, plus network and generation time.

## Validation

Review the log under `update-logs/`, then check:

```bash
git status --short
find data -name '*-out-*.csv' -size 0
python -m http.server 8000
```

Open `http://localhost:8000/` and also test `/authors2.html`, `/depts2.html`, `/statistics.html`, `/faq.html`, and `/charts2.html`. For GitHub project-page paths, prefer relative links and verify the site does not navigate to `csindexbr.org` as its own domain.

## Commit Scope

Commit regenerated static outputs such as:

```text
data/*-out-*.csv
data/depts/*.csv
data/depts/depts.html
data/profs.csv
data/profs/all-authors.csv
data/profs/search/*.csv
statistics.html
profs.html
sitemap.txt
```

Never commit `.venv/`, `cache/`, `local-backups/`, `update-logs/`, ZIP archives, logs, or temporary files.

After validation, review and publish:

```bash
git diff --stat
git status --short
git add <validated files>
git commit -m "Update GitHub Pages snapshot"
git push origin maintenance/github-pages-local-update
```

Merge to `master` only after review so GitHub Pages updates from the validated static snapshot.
