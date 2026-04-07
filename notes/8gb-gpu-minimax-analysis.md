# 8GB GPU for MiniMax M2.5 — Performance Analysis

## The Short Answer

An 8GB GPU provides **essentially zero benefit** over CPU-only inference for MiniMax M2.5 (230B MoE).
Single-user speed: **~1–3 tok/s**. Multi-user: **not viable**.

---

## Why 8GB Is Insufficient

MiniMax M2.5 smallest viable quantization (UD-Q3_K_XL) is **101GB**. An 8GB GPU can only hold:

- ~7.5GB of model weights (one pass at INT4 ≈ 4 bits/param)
- That covers roughly **7.5GB / 101GB ≈ 7%** of the model

The remaining 93% stays in system RAM and is processed on the CPU. The GPU handles only a thin
slice of the network — but the bottleneck is still RAM bandwidth for CPU-resident weights.

### Memory Layout (8GB GPU + 128GB RAM)
| Component | Location | Bandwidth |
|---|---|---|
| ~7–8GB model fragment | GPU VRAM | 300–600 GB/s (depending on GPU) |
| ~93–100GB remaining weights | System RAM | 60–150 GB/s (DDR5/LPDDR5) |
| Active experts (8/256) | CPU, sometimes partial GPU | CPU-bound |

The GPU cannot hold even a single full transformer layer of this model, so every token generation
requires a full CPU sweep.

---

## Benchmark Evidence

| Hardware | GPU VRAM | Result | GPU utilization |
|---|---|---|---|
| RTX 2080 Ti (11GB) + 128GB RAM | 11GB | ~3 tok/s | **3%** (GPU nearly idle) |
| RTX 3060 (8GB) estimate | 8GB | ~1–2 tok/s | <5% |
| CPU only (Xeon 8-core, DDR5) | — | ~2–3 tok/s | — |
| CPU only (Ryzen 9, DDR5 fast) | — | ~3–5 tok/s | — |

The 11GB RTX 2080 Ti result is the empirical anchor: 3% GPU utilization confirms the bottleneck
is entirely in system RAM throughput, not GPU compute. An 8GB GPU would be worse.

---

## Multi-User Viability

**Not viable for MiniMax M2.5 with an 8GB GPU.**

For concurrent users, you need:
1. Enough VRAM to batch multiple requests (KV cache scales with batch size × context length)
2. Fast prefill to handle incoming requests
3. Memory bandwidth that doesn't become the bottleneck at higher concurrency

An 8GB GPU fails on all three counts: KV cache for even 4 concurrent users at 4K context would
exceed available VRAM. All batching falls back to CPU.

---

## What 8GB GPU IS Useful For

| Task | Suitable? | Notes |
|---|---|---|
| MiniMax M2.5 230B | No | Model too large |
| Llama 3.1 8B (Q4) | Yes | Fits entirely in VRAM |
| Mistral 7B / Qwen 7B | Yes | Good single-user speed |
| Stable Diffusion XL | Yes | Fits with attention slicing |
| Embeddings (small models) | Yes | Fast batch embedding |

---

## Minimum GPU for Meaningful MiniMax M2.5 Improvement

| GPU VRAM | Effect | Minimum useful? |
|---|---|---|
| 8GB | Negligible (<5% GPU util) | No |
| 16GB | Marginal improvement (~10–15% of model in GPU) | No |
| **24GB** | Partial offload benefit begins | Marginal yes |
| **48GB** | Significant layers offloaded, ~15–20 tok/s | Yes |
| **80GB** | Most of model in VRAM, ~30–40 tok/s | Strong yes |
| **128GB** (Mac Studio M3 Ultra / DGX Spark) | Full model in unified memory | Full benefit |

**The practical minimum GPU for MiniMax M2.5 is 24GB VRAM** (RTX 3090/4090 or A5000).
Even then, with a 101GB model, you need 3–4× 24GB GPUs before you approach full GPU-resident inference.

---

## Recommendation

| Scenario | Recommendation |
|---|---|
| You have 8GB GPU + fast CPU + 128GB RAM | Use CPU-only inference; ignore the GPU |
| You want affordable MiniMax M2.5 performance | Mac Studio M2 Ultra (192GB) or M3 Max (128GB) |
| You want to use existing GPU investment | Only viable if GPU ≥ 24GB |
| Budget build for team/agentic use | See `128gb-minimax-m2.5.md` for full comparison |

---

## See Also

- `128gb-minimax-m2.5.md` — comprehensive hardware comparison
- `minimax-parallel-workloads.md` — multi-GPU and parallel architectures
- `nvidia-dgx-spark-minimax-analysis.md` — DGX Spark server throughput deep dive
