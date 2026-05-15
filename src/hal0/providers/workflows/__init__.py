"""Canonical ComfyUI workflow templates shipped with hal0.

Each template is a JSON file holding a ComfyUI graph in the *prompt* shape
(node-id keyed dict, the format ComfyUI's ``POST /prompt`` accepts), with
parameterised values (prompt text, latent width/height, seed, sampler
steps, etc.) that the translator in
:mod:`hal0.providers.comfyui_workflows` substitutes per-request.

Templates intentionally use the SIMPLEST graph that produces a usable image
for each model class — one positive-prompt CLIP encode, one empty latent,
one KSampler, one VAE decode, one SaveImage. Operators wanting fancier
graphs (LoRA stacks, ControlNet, regional prompts, …) can ship custom
workflows under ``/etc/hal0/workflows/``; that escape hatch isn't wired in
v1 but the file layout already supports it.

# NOTE: Stored as JSON (not Python dicts) so a designer can pop a workflow
# open in the ComfyUI graph editor, tweak it, "Save (API Format)", and
# drop the result back here without re-translating to Python literal
# syntax.
"""

from __future__ import annotations

__all__: list[str] = []
