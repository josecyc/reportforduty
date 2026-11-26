#!/usr/bin/env python3
"""Import the Max-of-K models from Gross et al. (arXiv:2406.11779) as plain .npz weights.

The authors published their trained checkpoints on the public wandb entity "gbmi". This
tool lists a project's model artifacts through wandb's public GraphQL API (no account),
downloads the .pth files, loads them with torch's restricted unpickler (tensors and plain
containers only; a stub stands in for transformer_lens's config class, so no third-party code
runs), and writes one .npz per seed with provenance (artifact id, URL, SHA-256).

    python3 tools/import_gbmi_models.py MaxOf4-3000-steps K4-v64 --vocab 64
    python3 tools/import_gbmi_models.py MaxOf10-3000-steps-nondeterministic K10-v64 --vocab 64

Needs torch and numpy (maintainers only; agents and the checker need only numpy).
Code and models: https://github.com/JasonGross/guarantees-based-mechanistic-interpretability (MIT).
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import sys
import tempfile
import types
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models" / "maxofk"


def _install_safe_globals():
    import torch

    class HookedTransformerConfig:  # stub that only keeps the pickled fields
        def __setstate__(self, state):
            self.__dict__.update(state if isinstance(state, dict) else {"state": state})

    HookedTransformerConfig.__module__ = "transformer_lens.HookedTransformerConfig"
    mod = types.ModuleType("transformer_lens.HookedTransformerConfig")
    mod.HookedTransformerConfig = HookedTransformerConfig
    sys.modules.setdefault("transformer_lens", types.ModuleType("transformer_lens"))
    sys.modules["transformer_lens.HookedTransformerConfig"] = mod
    from numpy._core.multiarray import scalar as _np_scalar

    def scalar(*args):
        return _np_scalar(*args)

    scalar.__module__, scalar.__qualname__ = "numpy.core.multiarray", "scalar"
    safe = [HookedTransformerConfig, codecs.encode, np.dtype, scalar]
    safe += [getattr(np.dtypes, n) for n in dir(np.dtypes) if isinstance(getattr(np.dtypes, n), type)]
    torch.serialization.add_safe_globals(safe)
    return torch


def list_files(project: str) -> list[dict]:
    files, cursor = [], None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        q = ('query { project(name: "%s", entityName: "gbmi") { artifactType(name: "model") { '
             'artifactCollections(first: 100%s) { pageInfo { hasNextPage endCursor } edges { node { name '
             'artifacts(first: 5) { edges { node { versionIndex createdAt files(first: 5) { edges { node { '
             'name sizeBytes directUrl } } } } } } } } } } } }') % (project, after)
        req = urllib.request.Request("https://api.wandb.ai/graphql", data=json.dumps({"query": q}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "rfd-import"})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        ac = d["data"]["project"]["artifactType"]["artifactCollections"]
        for e in ac["edges"]:
            for a in e["node"]["artifacts"]["edges"]:
                for f in a["node"]["files"]["edges"]:
                    files.append({"collection": e["node"]["name"], "version": a["node"]["versionIndex"],
                                  "created": a["node"]["createdAt"], **f["node"]})
        if not ac["pageInfo"]["hasNextPage"]:
            return files
        cursor = ac["pageInfo"]["endCursor"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("--vocab", type=int, default=64)
    ap.add_argument("--cache", default=None, help="folder of already downloaded .pth files")
    a = ap.parse_args()
    torch = _install_safe_globals()
    out = MODELS / a.out
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else Path(tempfile.mkdtemp(prefix="gbmi-"))
    files = list_files(a.project)
    chosen: dict[int, dict] = {}
    for f in files:
        path = cache / f["name"]
        if not path.exists():
            urllib.request.urlretrieve(f["directUrl"], path)
        blob = path.read_bytes()
        obj = torch.load(path, map_location="cpu", weights_only=True)
        rc, cfg, m = obj["run_config"], obj["model_config"].__dict__, obj["model"]
        if cfg["d_vocab"] != a.vocab:
            continue
        assert cfg["n_layers"] == 1 and cfg["n_heads"] == 1 and cfg["attn_only"] and cfg["normalization_type"] is None
        assert all(float(np.abs(v.numpy()).max()) == 0.0 for k2, v in m.items() if ".b_" in k2), "nonzero bias"
        seed = int(rc["seed"])
        rec = {"seed": seed, "file": f["name"], "created": f["created"], "wandb_id": obj.get("wandb_id"),
               "url": f["directUrl"].split("?")[0], "sha256": hashlib.sha256(blob).hexdigest(),
               "test_acc_reported": (obj.get("test_metrics") or [{}])[0].get("test_acc"),
               "weights": {k2: m[k2].numpy() for k2 in m}}
        # several versions of a seed: keep the most recently created checkpoint
        if seed not in chosen or rec["created"] > chosen[seed]["created"]:
            chosen[seed] = rec
    sources = []
    for seed, rec in sorted(chosen.items()):
        w = rec.pop("weights")
        np.savez(out / f"seed{seed}.npz",
                 W_E=w["embed.W_E"].astype(np.float32), W_pos=w["pos_embed.W_pos"].astype(np.float32),
                 W_Q=w["blocks.0.attn.W_Q"][0].astype(np.float32), W_K=w["blocks.0.attn.W_K"][0].astype(np.float32),
                 W_V=w["blocks.0.attn.W_V"][0].astype(np.float32), W_O=w["blocks.0.attn.W_O"][0].astype(np.float32),
                 W_U=w["unembed.W_U"].astype(np.float32))
        sources.append(rec)
    (out / "SOURCES.json").write_text(json.dumps({
        "paper": "Gross et al., Compact Proofs of Model Performance via Mechanistic Interpretability, NeurIPS 2024, arXiv:2406.11779",
        "code_license": "MIT, Copyright (c) 2024 Jason Gross; https://github.com/JasonGross/guarantees-based-mechanistic-interpretability",
        "wandb_project": f"gbmi/{a.project}", "vocab": a.vocab, "models": sources}, indent=1))
    print(f"{len(sources)} models written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
