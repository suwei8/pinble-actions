# pinble-actions

Scheduled GitHub Actions runner.

Three workflows poll a small HTTP feed and maintain a private dataset:

- **collect** — daily incremental collection job
- **snipe** — publish-window watcher
- **forecast** — periodic statistics job

All inputs, credentials and outputs live in a separate private repository;
this repo only contains workflow definitions.
