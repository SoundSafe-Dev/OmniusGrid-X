# Large assets: what is in the repository, what it costs, and what not to do

`backend/dataset` is **1.5 GB on disk** across 191 files — an LLM-generated correlation-AI
training corpus of roughly 500,000 scenarios, one `scenarios.jsonl` per domain across 51
domains. It is the largest thing in the repository by two orders of magnitude.

## The numbers, measured rather than estimated

| | |
|---|---|
| Packed size of the **whole repository** | **96 MB** |
| Of which `backend/dataset` blobs | **41 MB** (43% of all blob bytes) |
| `backend/dataset` **on disk after checkout** | **1.5 GB** |
| Compression ratio for the corpus | **~37×** (JSONL with a repeated schema) |

**The clone is not the problem; the checkout is.** An earlier audit reported this as "1.57 GB of
the 1.59 GB repository — 99% of every clone", which was wrong in an instructive way: it measured
`stat().st_size` on the working tree. Git stores the corpus compressed and deduplicated, so what
crosses the network is ~41 MB. What lands on a developer's disk, gets indexed by their editor,
walked by every `grep -r`, and written by all **28 CI checkout steps**, is 1.5 GB.

Measure the pack (`git count-objects -vH`), not the tree, before claiming a transfer cost.

## Do not delete it

`backend/scripts/generate_dataset_enhanced.py` produces these files, which makes them *output*
rather than *source* — and the usual conclusion, that output does not belong in git, does **not**
apply here:

* the generator **sets no random seed** anywhere, so a re-run produces different scenarios;
* it can call an LLM (`google.generativeai`), so a faithful re-run may also cost money and
  depends on a model that will not be the same model later.

So the corpus is not reproducible. Deleting it loses ~500,000 scenarios that cannot be
regenerated identically, and the fine-tuning results derived from them stop being explicable.
This is the difference between "generated" and "reproducible", and it is the whole reason the
obvious cleanup is the wrong move.

## What is done about it

**CI no longer checks it out.** All 28 `actions/checkout` steps across the three workflows use
sparse-checkout excluding `/backend/dataset/`. No job read it, so every run was writing 1.5 GB
for nothing.

**Developers can opt out per checkout**, with no effect on git:

```
make lean      # drop backend/dataset from this working tree
make unlean    # put it back
```

This is `git sparse-checkout`, so the files stay in history and in every other checkout — it
changes what is materialised on *your* disk, nothing else. Measured on this repository: 1.6 GB →
104 MB, with all source present.

**A fresh clone can skip it from the start:**

```
git clone --no-checkout <url> omniusgrid
cd omniusgrid
git sparse-checkout init --no-cone
printf '/*\n!/backend/dataset/\n' > .git/info/sparse-checkout
git checkout <branch>
```

**New corpora cannot land in git.** `.gitignore` now covers `train.jsonl`,
`validation.jsonl`, `training_data.jsonl`, `*_gemma4.jsonl` and `*.generated.jsonl` under
`backend/dataset/`. The next 500,000 scenarios go to an object store or a release artefact.

## What is still open

Getting the 41 MB out of *history* means rewriting it, which breaks every outstanding branch and
so belongs in the same coordinated window as the `HAMAD_IDE.pem` purge (**pool #49**), not in a
separate one. It is also the least valuable part: 41 MB of transfer is not what anybody is
feeling.

If the corpus is moved out of git entirely, it needs somewhere to live that a training run can
reach and a checksum in the repository so a run can prove which corpus it used. That is a
decision for whoever owns the fine-tuning work (**pool #1, #15**), not a repository-hygiene
change.

## The general rule

Anything generated, large, and **not reproducible** is an asset with a provenance problem, not a
build artefact. It needs a home, a checksum, and a documented way to fetch it — and until it has
those, deleting it is destroying data, however much it looks like clutter.
