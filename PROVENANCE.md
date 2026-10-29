# Provenance of the measurement runs

This repository was published with a fresh history for the thesis. The code was
developed in an earlier working repository, and every measurement run recorded
the commit of that repository it was measured with (`git_commit` and
`git_dirty` in each run's `meta.json`).

- The tag `thesis-final` holds the code of all runs and the analysis that
  generates the results. The measured scripts were fixed with the protocol on
  22 October 2026.
- `DEV_HISTORY.txt` in the data archive of the release `thesis-final` lists the
  commits of the working repository from which the runs were measured, with
  date and message, so each recorded `git_commit` can be looked up.
- Runs marked `git_dirty: true` were measured with changes that were committed
  afterwards; the run register in the data archive says which.
