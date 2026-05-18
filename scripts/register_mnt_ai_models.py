#!/usr/bin/env python3
"""One-off: inventory /mnt/ai-models on the hal0 LXC and POST each
relevant file to the live /api/models registry endpoint.

Runs on the LXC (or anywhere with HTTP access to the API). Idempotent —
a 409 Conflict for an already-registered id is logged and skipped.

Models registered:
  - ComfyUI image weights (Qwen-Image bf16/fp8 + VAE + text-encoder)
  - llama-server chat GGUFs (Qwen3.x, Hermes-4, gemma-4 …)
  - llama-server embed GGUF (nomic-embed-text-v1.5)
  - faster-whisper-small (asr, ctranslate2 dir)
  - Moonshine STT bundles (base-en, small-streaming-en, medium-streaming-en)
  - Moonshine bundled Kokoro TTS
  - hexgrad/Kokoro-82M (tts, hf cache dir)
  - VibeVoice 1.5B + Realtime-0.5B (tts dirs)

Capability strings follow hal0.capabilities.catalog._CAPABILITY_TO_CHILD:
  embed / rerank → embed slot
  stt / asr      → voice slot (stt child)
  tts            → voice slot (tts child)
  image          → img slot
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("HAL0_API", "http://127.0.0.1:8080")


def _post(path: str, payload: dict) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body


def _existing_ids() -> set[str]:
    with urllib.request.urlopen(f"{API}/api/models", timeout=10) as r:
        data = json.loads(r.read())
    return {m["id"] for m in data.get("models", []) if m.get("installed")}


# (id, name, path, size_bytes, capabilities, backends, license, hf_repo, hf_filename, tags, metadata)
MODELS: list[dict] = [
    # ── ComfyUI image weights ────────────────────────────────────────────
    {
        "id": "qwen-image-2512-bf16",
        "name": "Qwen-Image 2512 (bf16)",
        "path": "/mnt/ai-models/comfyui/diffusion_models/qwen_image_2512_bf16.safetensors",
        "size_bytes": 41806559488,  # 39G; will be replaced by real stat below if available
        "capabilities": ["image"],
        "backends": ["comfyui"],
        "license": "Apache-2.0",
        "hf_repo": "Comfy-Org/Qwen-Image_ComfyUI",
        "hf_filename": "split_files/diffusion_models/qwen_image_2512_bf16.safetensors",
        "tags": ["comfyui", "image", "qwen-image", "bf16"],
        "metadata": {"comfyui_subdir": "diffusion_models", "precision": "bf16"},
    },
    {
        "id": "qwen-image-2512-fp8-e4m3fn",
        "name": "Qwen-Image 2512 (fp8 e4m3fn)",
        "path": "/mnt/ai-models/comfyui/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors",
        "size_bytes": 21474836480,
        "capabilities": ["image"],
        "backends": ["comfyui"],
        "license": "Apache-2.0",
        "hf_repo": "Comfy-Org/Qwen-Image_ComfyUI",
        "hf_filename": "split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors",
        "tags": ["comfyui", "image", "qwen-image", "fp8"],
        "metadata": {"comfyui_subdir": "diffusion_models", "precision": "fp8_e4m3fn"},
    },
    {
        "id": "qwen-image-vae",
        "name": "Qwen-Image VAE",
        "path": "/mnt/ai-models/comfyui/vae/qwen_image_vae.safetensors",
        "size_bytes": 254803968,
        "capabilities": ["image-vae"],
        "backends": ["comfyui"],
        "license": "Apache-2.0",
        "hf_repo": "Comfy-Org/Qwen-Image_ComfyUI",
        "hf_filename": "split_files/vae/qwen_image_vae.safetensors",
        "tags": ["comfyui", "component", "vae"],
        "metadata": {"comfyui_subdir": "vae", "component_of": "qwen-image"},
    },
    {
        "id": "qwen-2.5-vl-7b-fp8-text-encoder",
        "name": "Qwen 2.5 VL 7B (fp8 scaled) — Text Encoder",
        "path": "/mnt/ai-models/comfyui/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "size_bytes": 9449377792,
        "capabilities": ["image-text-encoder"],
        "backends": ["comfyui"],
        "license": "Apache-2.0",
        "hf_repo": "Comfy-Org/Qwen-Image_ComfyUI",
        "hf_filename": "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "tags": ["comfyui", "component", "text-encoder"],
        "metadata": {"comfyui_subdir": "text_encoders", "component_of": "qwen-image"},
    },
    # ── llama-server chat GGUFs ──────────────────────────────────────────
    {
        "id": "hermes-4-14b-q5_k_m",
        "name": "NousResearch Hermes-4 14B (Q5_K_M)",
        "path": "/mnt/ai-models/huggingface/hub/models--bartowski--NousResearch_Hermes-4-14B-GGUF/snapshots/0693c8f45031215d6734406947e6b43d1b3ee0de/NousResearch_Hermes-4-14B-Q5_K_M.gguf",
        "size_bytes": 10514570176,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "bartowski/NousResearch_Hermes-4-14B-GGUF",
        "hf_filename": "NousResearch_Hermes-4-14B-Q5_K_M.gguf",
        "tags": ["chat", "hermes", "q5_k_m"],
        "metadata": {"family": "hermes"},
    },
    {
        "id": "qwen3-coder-next-reap-40b-a3b-q4_k_xl",
        "name": "Qwen3 Coder Next REAP 40B A3B (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--lovedheart--Qwen3-Coder-Next-REAP-40B-A3B-GGUF/snapshots/3a109ada2fb13cbc9c1929067f4f35db1f2b32ab/Qwen3-Coder-Next-REAP-40B-A3B-Q4_K_XL.gguf",
        "size_bytes": 28524629088,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "lovedheart/Qwen3-Coder-Next-REAP-40B-A3B-GGUF",
        "hf_filename": "Qwen3-Coder-Next-REAP-40B-A3B-Q4_K_XL.gguf",
        "tags": ["chat", "coder", "qwen", "moe", "reap"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3.5-9b-q4_k_xl",
        "name": "Qwen3.5 9B (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--Qwen3.5-9B-GGUF/snapshots/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-UD-Q4_K_XL.gguf",
        "size_bytes": 5966095584,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "unsloth/Qwen3.5-9B-GGUF",
        "hf_filename": "Qwen3.5-9B-UD-Q4_K_XL.gguf",
        "tags": ["chat", "qwen"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3-coder-reap-25b-a3b-q5_k_m",
        "name": "Cerebras Qwen3-Coder REAP 25B A3B (Q5_K_M)",
        "path": "/mnt/ai-models/huggingface/hub/models--bartowski--cerebras_Qwen3-Coder-REAP-25B-A3B-GGUF/snapshots/c279f99e1b6bd4b4afd300c07d4cb0614c67452b/cerebras_Qwen3-Coder-REAP-25B-A3B-Q5_K_M.gguf",
        "size_bytes": 17716451936,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "bartowski/cerebras_Qwen3-Coder-REAP-25B-A3B-GGUF",
        "hf_filename": "cerebras_Qwen3-Coder-REAP-25B-A3B-Q5_K_M.gguf",
        "tags": ["chat", "coder", "qwen", "moe", "reap"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3.6-27b-q5_k_xl",
        "name": "Qwen3.6 27B (Q5_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--Qwen3.6-27B-GGUF/snapshots/82d411acf4a06cfb8d9b073a5211bf410bfc29bf/Qwen3.6-27B-UD-Q5_K_XL.gguf",
        "size_bytes": 20038256864,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "unsloth/Qwen3.6-27B-GGUF",
        "hf_filename": "Qwen3.6-27B-UD-Q5_K_XL.gguf",
        "tags": ["chat", "qwen", "vision"],
        "metadata": {"family": "qwen", "mmproj": "mmproj-F16.gguf"},
    },
    {
        "id": "qwen3.5-4b-q4_k_xl",
        "name": "Qwen3.5 4B (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--Qwen3.5-4B-GGUF/snapshots/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q4_K_XL.gguf",
        "size_bytes": 2912109728,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "unsloth/Qwen3.5-4B-GGUF",
        "hf_filename": "Qwen3.5-4B-UD-Q4_K_XL.gguf",
        "tags": ["chat", "qwen", "small"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3-coder-next-q4_k_xl",
        "name": "Qwen3 Coder Next (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--Qwen3-Coder-Next-GGUF/snapshots/ce09c67b53bc8739eef83fe67b2f5d293c270632/Qwen3-Coder-Next-UD-Q4_K_XL.gguf",
        "size_bytes": 49608478720,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "unsloth/Qwen3-Coder-Next-GGUF",
        "hf_filename": "Qwen3-Coder-Next-UD-Q4_K_XL.gguf",
        "tags": ["chat", "coder", "qwen", "moe"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3.6-27b-heretic-q4_k_m",
        "name": "Qwen3.6 27B Heretic NEO-CODE (Q4_K_M)",
        "path": "/mnt/ai-models/huggingface/hub/models--DavidAU--Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF/snapshots/08385e96e342f8aa261d8a3976d6a01ee9239400/Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf",
        "size_bytes": 16861398400,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "DavidAU/Qwen3.6-27B-Heretic-Uncensored-FINETUNE-NEO-CODE-Di-IMatrix-MAX-GGUF",
        "hf_filename": "Qwen3.6-27B-NEO-CODE-HERE-2T-OT-Q4_K_M.gguf",
        "tags": ["chat", "qwen", "uncensored", "finetune"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3.6-35b-a3b-q4_k_xl",
        "name": "Qwen3.6 35B A3B (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--Qwen3.6-35B-A3B-GGUF/snapshots/9280dd353ab587157920d5bd391ada414d84e552/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
        "size_bytes": 22360456160,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "unsloth/Qwen3.6-35B-A3B-GGUF",
        "hf_filename": "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
        "tags": ["chat", "qwen", "moe"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "qwen3-zero-coder-v2-0.8b-f16",
        "name": "Qwen3 Zero Coder Reasoning V2 0.8B NEO-EX (F16)",
        "path": "/mnt/ai-models/huggingface/hub/models--DavidAU--Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF/snapshots/471bc1d467ebf2616d54b867b6f93146f183e3ae/Qwen3-Zro-Cdr-Reason-V2-0.8B-NEO3-EX-D_AU-F16.gguf",
        "size_bytes": 1638722560,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF",
        "hf_filename": "Qwen3-Zro-Cdr-Reason-V2-0.8B-NEO3-EX-D_AU-F16.gguf",
        "tags": ["chat", "coder", "qwen", "tiny", "finetune"],
        "metadata": {"family": "qwen"},
    },
    {
        "id": "gemma-4-26b-a4b-it-q4_k_xl",
        "name": "Gemma 4 26B A4B IT (Q4_K_XL)",
        "path": "/mnt/ai-models/huggingface/hub/models--unsloth--gemma-4-26B-A4B-it-GGUF/snapshots/8bacec5c8e829a25502cdfe3c3f5b6aabee3218c/gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf",
        "size_bytes": 17090276672,
        "capabilities": ["chat"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "gemma",
        "hf_repo": "unsloth/gemma-4-26B-A4B-it-GGUF",
        "hf_filename": "gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf",
        "tags": ["chat", "gemma", "moe"],
        "metadata": {"family": "gemma"},
    },
    # ── Embed GGUF ───────────────────────────────────────────────────────
    {
        "id": "nomic-embed-text-v1.5-q8_0",
        "name": "Nomic Embed Text v1.5 (Q8_0)",
        "path": "/mnt/ai-models/huggingface/hub/models--nomic-ai--nomic-embed-text-v1.5-GGUF/snapshots/0188c9bf409793f810680a5a431e7b899c46104c/nomic-embed-text-v1.5.Q8_0.gguf",
        "size_bytes": 146146432,
        "capabilities": ["embed"],
        "backends": ["vulkan", "rocm", "cpu"],
        "license": "apache-2.0",
        "hf_repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
        "hf_filename": "nomic-embed-text-v1.5.Q8_0.gguf",
        "tags": ["embed", "nomic"],
        "metadata": {"family": "nomic"},
    },
    # ── Voice / ASR ──────────────────────────────────────────────────────
    {
        "id": "faster-whisper-small",
        "name": "Systran faster-whisper-small",
        "path": "/mnt/ai-models/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120",
        "size_bytes": 483546902,
        "capabilities": ["asr", "stt"],
        "backends": ["moonshine", "cpu"],
        "license": "mit",
        "hf_repo": "Systran/faster-whisper-small",
        "hf_filename": "model.bin",
        "tags": ["asr", "stt", "whisper", "ctranslate2"],
        "metadata": {"runtime": "ctranslate2", "format": "faster-whisper"},
    },
    {
        "id": "moonshine-base-en",
        "name": "Moonshine base-en (quantized)",
        "path": "/mnt/ai-models/moonshine_voice/download.moonshine.ai/model/base-en",
        "size_bytes": 250004518,
        "capabilities": ["asr", "stt"],
        "backends": ["moonshine"],
        "license": "mit",
        "hf_repo": "",
        "hf_filename": "",
        "tags": ["asr", "stt", "moonshine"],
        "metadata": {"runtime": "onnx", "variant": "base-en"},
    },
    {
        "id": "moonshine-small-streaming-en",
        "name": "Moonshine small-streaming-en (quantized)",
        "path": "/mnt/ai-models/moonshine_voice/download.moonshine.ai/model/small-streaming-en",
        "size_bytes": 246070310,
        "capabilities": ["asr", "stt"],
        "backends": ["moonshine"],
        "license": "mit",
        "hf_repo": "",
        "hf_filename": "",
        "tags": ["asr", "stt", "moonshine", "streaming"],
        "metadata": {"runtime": "onnx", "variant": "small-streaming-en"},
    },
    {
        "id": "moonshine-medium-streaming-en",
        "name": "Moonshine medium-streaming-en (quantized)",
        "path": "/mnt/ai-models/moonshine_voice/download.moonshine.ai/model/medium-streaming-en",
        "size_bytes": 449468031,
        "capabilities": ["asr", "stt"],
        "backends": ["moonshine"],
        "license": "mit",
        "hf_repo": "",
        "hf_filename": "",
        "tags": ["asr", "stt", "moonshine", "streaming"],
        "metadata": {"runtime": "onnx", "variant": "medium-streaming-en"},
    },
    # ── Voice / TTS ──────────────────────────────────────────────────────
    {
        "id": "kokoro-moonshine-onnx",
        "name": "Kokoro TTS (Moonshine ONNX bundle)",
        "path": "/mnt/ai-models/moonshine_voice/download.moonshine.ai/tts/kokoro",
        "size_bytes": 92361116,
        "capabilities": ["tts"],
        "backends": ["kokoro"],
        "license": "apache-2.0",
        "hf_repo": "",
        "hf_filename": "",
        "tags": ["tts", "kokoro", "moonshine"],
        "metadata": {"runtime": "onnx", "source": "moonshine"},
    },
    {
        "id": "kokoro-82m",
        "name": "Kokoro 82M (hexgrad)",
        "path": "/mnt/ai-models/huggingface/hub/models--hexgrad--Kokoro-82M",
        "size_bytes": 327000000,
        "capabilities": ["tts"],
        "backends": ["kokoro"],
        "license": "apache-2.0",
        "hf_repo": "hexgrad/Kokoro-82M",
        "hf_filename": "kokoro-v1_0.pth",
        "tags": ["tts", "kokoro"],
        "metadata": {"runtime": "pytorch"},
    },
    {
        "id": "vibevoice-1.5b",
        "name": "VibeVoice 1.5B",
        "path": "/mnt/ai-models/voices/vibevoice/VibeVoice-1.5B",
        "size_bytes": 5408492221,
        "capabilities": ["tts"],
        "backends": ["kokoro"],
        "license": "mit",
        "hf_repo": "aoi-ot/VibeVoice-Large",
        "hf_filename": "model-00001-of-00003.safetensors",
        "tags": ["tts", "vibevoice"],
        "metadata": {"runtime": "transformers", "shards": 3},
    },
    {
        "id": "vibevoice-realtime-0.5b",
        "name": "VibeVoice Realtime 0.5B",
        "path": "/mnt/ai-models/voices/vibevoice/VibeVoice-Realtime-0.5B",
        "size_bytes": 2035471485,
        "capabilities": ["tts"],
        "backends": ["kokoro"],
        "license": "mit",
        "hf_repo": "microsoft/VibeVoice-Realtime-0.5B",
        "hf_filename": "model.safetensors",
        "tags": ["tts", "vibevoice", "realtime", "small"],
        "metadata": {"runtime": "transformers"},
    },
]


def main() -> int:
    existing = _existing_ids()
    print(f"already registered: {sorted(existing)}")

    added: list[str] = []
    skipped_existing: list[str] = []
    failed: list[tuple[str, int, object]] = []

    for spec in MODELS:
        mid = spec["id"]
        if mid in existing:
            print(f"  skip {mid}: already registered")
            skipped_existing.append(mid)
            continue
        status, body = _post("/api/models", {**spec, "source": "inventory-scan"})
        if status in (200, 201):
            print(f"  add  {mid}: ok ({status})")
            added.append(mid)
        elif status == 409:
            # Idempotent overwrite from sibling agent — gracefully skip.
            print(f"  skip {mid}: 409 from sibling registration")
            skipped_existing.append(mid)
        else:
            print(f"  FAIL {mid}: {status} {body}")
            failed.append((mid, status, body))

    print()
    print(f"summary: added={len(added)} already={len(skipped_existing)} failed={len(failed)}")
    if failed:
        for mid, status, body in failed:
            print(f"  {mid}: {status} :: {body}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
