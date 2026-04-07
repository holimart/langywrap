# MiniMax M2.5 Local Inference — Complete Hardware Guide (Mar 2026)

## First: Model Family Clarification

"MiniMax 2.5" actually refers to **MiniMax-M2.5** (Feb 2026), not the older 456B Text-01/M1 line. These are very different in local inference feasibility:

| Model | Released | Total Params | Active/Token | Context | Local Inference |
|---|---|---|---|---|---|
| MiniMax-Text-01 | Jan 2025 | 456B | 45.9B | 1M | **Not possible** — no GGUF support |
| MiniMax-M1 | Jun 2025 | 456B | 45.9B | 1M | **Not possible** — needs 8× 90GB GPUs minimum |
| MiniMax-M2 | Oct 2025 | 229B | ~10B | 200K | Yes (llama.cpp supported) |
| MiniMax-M2.1 | Dec 2025 | 229B | ~10B | 200K | Yes |
| **MiniMax-M2.5** | Feb 2026 | 230B | ~10B | 200K | **Yes — practical target** |

> **Important:** Text-01 and M1 architecture (`MiniMaxM1ForCausalLM`) is not supported by llama.cpp. An experimental community branch exists but is a proof-of-concept only. The rest of this guide covers **M2.5 (and M2/M2.1 which share the same architecture).**

---

## Quantization Reference Table (MiniMax-M2.5, GGUF)

| Quantization | File Size | Min RAM/VRAM | Quality | Notes |
|---|---|---|---|---|
| BF16 (unquantized) | 457 GB | 512 GB | Reference | Official FP8 weights also available |
| Q8_0 | 243 GB | 256 GB | Near-lossless | Fits 512GB Mac |
| Q6_K | 188 GB | 196 GB | Very high | Fits M3 Ultra 192GB |
| Q5_K_M | 162 GB | 170 GB | High | |
| Q4_K_M | 139 GB | 148 GB | Good (default) | bartowski/unsloth repos |
| IQ4_XS | 122 GB | 130 GB | Good | |
| **UD-Q3_K_XL** | **~101 GB** | **128 GB** | **~6-bit quality** | **Unsloth Dynamic 2.0 — sweet spot for 128GB** |
| Q3_K_L | 108 GB | 120 GB | Lower | |
| IQ2_KS | 70 GB | 80 GB | Degraded | Minimum viable for 96GB |
| IQ1_S | ~47 GB | 64 GB | Poor | CPU-only last resort |

> **Unsloth Dynamic 2.0:** Keeps critical attention/embedding layers at 8–16-bit precision, aggressively compresses expert layers. 3-bit average with quality closer to 6-bit. This is what enables running the 230B model in 128GB.

GGUF sources: [unsloth/MiniMax-M2.5-GGUF](https://huggingface.co/unsloth/MiniMax-M2.5-GGUF), [ubergarm/MiniMax-M2.5-GGUF](https://huggingface.co/ubergarm/MiniMax-M2.5-GGUF), [bartowski/MiniMaxAI_MiniMax-M2.1-GGUF](https://huggingface.co/bartowski/MiniMaxAI_MiniMax-M2.1-GGUF)

---

## Main Hardware Comparison Table

> **Decode tok/s** = single-user token generation (the number you feel). **Prefill tok/s** = prompt processing speed. Different inference stacks produce very different numbers.

| Hardware Config | Memory | Quantization | Decode tok/s | Prefill tok/s | Hardware Cost | Power Draw | Power/mo | Inference Stack | Source / Confidence |
|---|---|---|---|---|---|---|---|---|---|
| **MiniMax Cloud API** | (cloud) | BF16/native | 50–100 | fast | $0 upfront | — | ~$300–500+/mo API | — | Official |
| **NVIDIA DGX Spark** (GB10 chip) | 128 GB unified | Unsloth 3-bit | ~26 | ~473 | ~$4,500 | ~200W | ~$15/mo | llama.cpp | [re:cinq blog](https://re-cinq.com/blog/minimax-m2-5-nvidia-dgx) ✓ verified |
| **NVIDIA DGX Spark** (GB10 chip) | 128 GB unified | NVFP4 (Blackwell-native) | **~720 peak** | **~3,342** | ~$4,500 | ~200W | ~$15/mo | vLLM / custom | [NVIDIA forums](https://forums.developer.nvidia.com/t/minimax-2-5-reap-nvfp4-on-single-dgx-spark/361248) ✓ verified |
| **Mac Studio M4 Max** | 128 GB unified | UD-Q3_K_XL | ~20–25 | — | ~$2,799–3,999 | ~180W | ~$13/mo | llama.cpp / Metal | [Unsloth docs](https://unsloth.ai/docs/models/minimax-m25) ⚠ estimate |
| **Mac Studio M3 Ultra** | 192 GB unified | 3-bit / Q5 | ~20–25 | — | ~$5,499 | ~200W | ~$15/mo | LM Studio / llama.cpp | [Unsloth](https://unsloth.ai/docs/models/minimax-m25) + [Purple Maia Labs](https://blog.labs.purplemaia.org/from-benchmarks-to-builders-running-minimax-m2-1-on-our-mac-studio/) ⚠ mostly estimate |
| **Mac Studio M3 Ultra** | 512 GB unified | Q8_0 (243 GB) | ~10+ | — | ~$14,099 (maxed) | ~250W | ~$18/mo | Ollama / llama.cpp | Community reports ⚠ unverified |
| **2× RTX 6000 Ada** (96 GB VRAM) | 96 GB VRAM | NVFP4 | ~83 (1 user); 1000+ tok/s (32 concurrent) | — | ~$20,000 | ~1,200W | ~$87/mo | vLLM | [@TheAhmadOsman on X](https://x.com/TheAhmadOsman/status/2022925134496252395) ✓ |
| **RTX PRO 6000 Blackwell ×1** (96 GB) | 96 GB VRAM | ~Q4_K (model offloaded to RAM) | ~15–20 est. | ~270 tok/s (Mistral ref) | ~$7,999 | ~600W | ~$43/mo | llama.cpp | [StorageReview](https://www.storagereview.com/review/nvidia-rtx-pro-6000-workstation-gpu-review-blackwell-architecture-and-96-gb-for-pro-workflows) + extrapolation ⚠ |
| **8× RTX PRO 6000 Blackwell** (768 GB VRAM) | 768 GB VRAM | FP8 | 70 (1 user); 122 (2 concurrent) | — | ~$64,000 | ~5,000W | ~$360/mo | modified vLLM + SGLang | [r/LocalLLaMA / aihaberleri](https://aihaberleri.org/en/news/minimax-25-ai-model-runs-locally-on-8x-pro-6000-gpus-with-fp8-precision) ✓ |
| **4× H100 80GB** (320 GB VRAM) | 320 GB VRAM | FP8 (official) | ~50–80 est. | — | ~$140–160K new; ~$38–56K used | ~3,500W | ~$252/mo | vLLM (TP=4) | [vLLM docs](https://docs.vllm.ai/projects/recipes/en/latest/MiniMax/MiniMax-M2.html) — reference config, no MiniMax-specific tok/s |
| **RTX 4090D ×1** (48 GB, China variant) | 48 GB VRAM + CPU RAM | Q4_K_M (partial offload) | ~16–20 | ~67 prompt | ~$5,000 | ~500W | ~$36/mo | llama.cpp | [HuggingFace discussion](https://huggingface.co/unsloth/MiniMax-M2.1-GGUF/discussions/2) ✓ |
| **RTX 4090 ×4** (96 GB VRAM) | 96 GB VRAM + 128 GB RAM | IQ3_K or IQ4_XS | ~20–30 est. | — | ~$8,000–14,000 | ~1,800W | ~$130/mo | llama.cpp | Extrapolated from DGX Spark (same VRAM budget) ⚠ |
| **Mixed: 72 GB old VRAM** (Xeon + P100s) | 72 GB VRAM + 256 GB DDR4 | UD-Q4_K_XL | ~20 | — | ~$5–8K (used) | ~800W | ~$58/mo | llama.cpp | [HuggingFace discussion](https://huggingface.co/unsloth/MiniMax-M2.1-GGUF/discussions/2) ✓ |
| **KTransformers: 2× RTX 5090** + EPYC CPU | 64 GB VRAM + 256 GB RAM | mixed | ~20–30; **4.5× prefill** vs llama.cpp | — | ~$6–8K | ~1,000W | ~$72/mo | KTransformers (AVX FP8 MoE) | [ktransformers repo](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md) ⚠ |
| **CPU + 192 GB DDR5 + RTX 2080 Ti** (11 GB) | 11 GB VRAM + 192 GB RAM | i1-Q4_K_M | **~2–3** | — | ~$3–4K | ~400W | ~$29/mo | llama.cpp (CPU-bottlenecked) | [llama.cpp discussion #19069](https://github.com/ggml-org/llama.cpp/discussions/19069) ✓ |
| **CPU only** | 96 GB RAM | IQ1_S (47 GB) | **~2.8** | — | ~$1–2K | ~150W | ~$11/mo | llama.cpp | [SonuSahani blog](https://sonusahani.com/blogs/minimax-m21-local) ✓ — heavily degraded quality |

> ✓ = community-verified result with methodology / ⚠ = estimate or single-source

---

## For 128 GB Hardware Specifically

The Unsloth UD-Q3_K_XL quant (101 GB) is purpose-built for this tier:

| 128 GB Option | Architecture | Key Feature | Tok/s | Cost | Verdict |
|---|---|---|---|---|---|
| **Mac Studio M4 Max 128GB** | Apple Silicon (M4 Max) | Unified memory, Metal GPU, silent, low power | ~20–25 | ~$2,799–3,999 | Best entry point; simple setup via LM Studio/Ollama |
| **NVIDIA DGX Spark** | GB10 (Blackwell, 20× GPU cores) | NVFP4 support = 720 tok/s in server mode | 26 (single) / 720 (throughput) | ~$4,500 | Best performance at this tier; Blackwell NVFP4 is a different league for throughput |
| **DIY PC: 128 GB DDR5 + RTX 4090 ×4** | x86 CPU + 4× PCIe GPU | Configurable, upgradeable | ~20–30 est. | ~$6,000–10,000 | More complex; power-hungry; 96 GB VRAM fits IQ3/IQ4 variants in VRAM entirely |
| **DIY PC: 128 GB DDR5 + RTX PRO 6000** | x86 CPU + 1× PCIe GPU (96 GB) | Single GPU, 96 GB VRAM covers most of model | ~15–20 est. | ~$9,000–11,000 | Simpler than 4×4090; one slot, better long-context |

---

## Cost / ROI Analysis

| Scenario | Monthly API Cost | Hardware Investment | Break-even | Notes |
|---|---|---|---|---|
| Light usage (<500K output tokens/mo) | ~$60 | Any local hw | Never | Cloud wins; stay on API |
| Developer (moderate) | ~$300–500/mo | DGX Spark $4,500 | ~9–11 months | [re:cinq calculation](https://re-cinq.com/blog/minimax-m2-5-nvidia-dgx) |
| Developer (heavy) | ~$500–800/mo | Mac Studio M3 Ultra 192GB $5,499 | ~8–11 months | After breakeven: ~$20/mo electricity |
| Small team (3–5 devs) | ~$1,500–2,500/mo | 8× RTX PRO 6000 $64,000 | ~26–43 months | Only viable at very high token volumes |
| Enterprise | ~$10K+/mo | 4× H100 $56K used | ~6 months | Also enables training/fine-tuning |

**API pricing** (MiniMax M2.5 as of Feb 2026):
- Standard: $0.30/M input, $1.20/M output
- Lightning (100 tok/s): $0.30/M input, $2.40/M output
- At 100 tok/s continuous: ~**$1.00/hour**

---

## Component Pricing (March 2026)

| Component | Price Range | Notes |
|---|---|---|
| RTX 4090 (24 GB) | $2,000–3,600 new / $1,800–2,200 used | Production ceased Oct 2024; prices rising |
| RTX PRO 6000 Blackwell (96 GB) | ~$7,999 | Dropped from $9,299; strong LLM card |
| A100 80GB (used/refurbished) | $9,500–14,000 | PCIe version standalone; SXM needs server |
| H100 80GB SXM (new) | $35,000–40,000 | HBM shortage pushing prices up |
| Mac Studio M4 Max 128GB | ~$3,200–4,000 configured | Best value per GB at 128GB tier |
| Mac Studio M3 Ultra 192GB | ~$5,499 | No M4 Ultra yet; M5 Ultra expected mid-2026 |
| Mac Studio M3 Ultra 512GB | ~$14,099 (maxed) | |
| DDR5 128GB kit | **$700–1,500** ⚠ | Was $280 in early 2025 — DRAM shortage |
| 2TB NVMe SSD | $140–200 | +$25 vs prior year; NAND shortage |
| 4TB NVMe SSD | $250–400 | |

> **Warning on RAM/SSD prices:** The AI-driven DRAM/NAND shortage has driven DDR5 prices up 3–5× since early 2025. Budget DDR5 128GB at $700–1,500 and check prices weekly — they fluctuate hourly.

---

## Inference Stack Notes

| Stack | Best For | MiniMax M2.5 Support |
|---|---|---|
| **llama.cpp** | Consumer hardware, Apple Silicon, CPU+GPU hybrid | Full support (PR #18399 merged) |
| **Ollama** | Easy setup on top of llama.cpp | Works; [Ollama library](https://ollama.com/library/minimax-m2) |
| **LM Studio** | GUI on Mac/Windows, llama.cpp backend | Works; tested on M3 Ultra |
| **vLLM** | Multi-GPU throughput (TP=4/8), server workloads | Full support; TP + EP, no PP |
| **SGLang** | High-throughput serving | Support via MiniMax collaboration |
| **KTransformers** | CPU/GPU hybrid with AVX FP8 MoE kernel | [Tutorial available](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md); 4.5× prefill vs llama.cpp |
| **MLX** | Apple Silicon only | vllm-mlx works but crashes at high concurrency/context |

---

## Key Caveats

1. **Most 20–25 tok/s Mac numbers originate from a single Unsloth marketing post** and have been copy-pasted across guides without independent verification. Treat as plausible estimates, not hard benchmarks.

2. **No M4 Ultra exists yet.** The 2025 Mac Studio ships M4 Max (≤128 GB) or M3 Ultra (≤192 GB / ≤512 GB). M4 Ultra/M5 Ultra are expected mid-2026.

3. **DGX Spark NVFP4 720 tok/s** is server-mode throughput (many batched requests), not single-user latency. Single-user with llama.cpp is ~26 tok/s.

4. **RTX 4090D 48GB** is a China-market variant. Regular RTX 4090 has 24 GB — can partially offload layers but most model stays in CPU RAM.

5. **NVMe SSD offloading** (llama.cpp mmap when model > RAM) reduces to 0.5–2 tok/s for a 100+ GB model — not practically useful.

6. **Pipeline parallelism is unsupported** in vLLM/SGLang for this model family. Use tensor parallelism or expert parallelism instead.

---

## Key Sources

- [MiniMax-M2.5: The $1/hour Frontier Model — mlabonne (HuggingFace Blog)](https://huggingface.co/blog/mlabonne/minimax-m25)
- [Running MiniMax M2.5 Locally on NVIDIA DGX Spark — re:cinq](https://re-cinq.com/blog/minimax-m2-5-nvidia-dgx)
- [MiniMax-M2.5: How to Run Guide — Unsloth](https://unsloth.ai/docs/models/minimax-m25)
- [unsloth/MiniMax-M2.5-GGUF](https://huggingface.co/unsloth/MiniMax-M2.5-GGUF)
- [ubergarm/MiniMax-M2.5-GGUF](https://huggingface.co/ubergarm/MiniMax-M2.5-GGUF)
- [vLLM MiniMax-M2 Series Usage Guide](https://docs.vllm.ai/projects/recipes/en/latest/MiniMax/MiniMax-M2.html)
- [llama.cpp Discussion #19069 — 192GB RAM + RTX 2080 Ti result](https://github.com/ggml-org/llama.cpp/discussions/19069)
- [unsloth/MiniMax-M2.1-GGUF Discussion #2 — 20 tok/s on 72GB VRAM](https://huggingface.co/unsloth/MiniMax-M2.1-GGUF/discussions/2)
- [NVIDIA Forums — MiniMax M2.5 NVFP4 on DGX Spark](https://forums.developer.nvidia.com/t/minimax-2-5-reap-nvfp4-on-single-dgx-spark/361248)
- [Purple Maia Labs — Running MiniMax M2.1 on Mac Studio M3 Ultra](https://blog.labs.purplemaia.org/from-benchmarks-to-builders-running-minimax-m2-1-on-our-mac-studio/)
- [MiniMax M2.5 on 8× RTX PRO 6000 FP8](https://aihaberleri.org/en/news/minimax-25-ai-model-runs-locally-on-8x-pro-6000-gpus-with-fp8-precision)
- [ktransformers MiniMax-M2.5 Guide](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md)
- [Tom's Hardware RAM Price Index 2026](https://www.tomshardware.com/pc-components/ram/ram-price-index-2026-lowest-price-on-ddr5-and-ddr4-memory-of-all-capacities)
- [RTX PRO 6000 StorageReview LLM Benchmarks](https://www.storagereview.com/review/nvidia-rtx-pro-6000-workstation-gpu-review-blackwell-architecture-and-96-gb-for-pro-workflows)
- [MiniMax API Pricing](https://platform.minimax.io/docs/guides/pricing-paygo)
