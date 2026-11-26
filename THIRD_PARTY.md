# Third-party material

| What | Where | License |
|---|---|---|
| Max-of-4 and Max-of-10 transformer weights from Gross et al., "Compact Proofs of Model Performance via Mechanistic Interpretability" (arXiv:2406.11779) | `models/maxofk/` Downloaded from the paper's public Weights & Biases runs. The authors' code is MIT, Copyright (c) 2024 Jason Gross; no separate license is stated for the weights. See `models/maxofk/LICENSE`. |
| Mathlib (fetched by Lake when the Lean training ground is set up; not included) | `lean/` dependency | Apache 2.0 |

Two optional theaters read other projects at run time; nothing from them is included here:

- **Treaty wargames** read AI Race's Verified Race engine (`sources/race_env.py`) from a local
  checkout set in `rfd.local.json` or `RFD_AIRACE`.
- **Who believes what** and the **intelligence desk** read the Futuras map of views
  (`lib/views.json`, `lib/views.ts`) from a checkout set in `rfd.local.json` or `RFD_FUTURAS`.
