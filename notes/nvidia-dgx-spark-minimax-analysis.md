# NVIDIA DGX Spark — MiniMax M2.5 Server Throughput Deep Dive (Mar 2026)

## The Key Twist: REAP-139B, Not Full 230B

The high throughput numbers are for **`cerebras/MiniMax-M2.5-REAP-139B`** — a pruned variant, not the full model. **REAP** = *Router-weighted Expert Activation Pruning* (Cerebras technique):

- Removes 40% of experts (256 → 154) based on router gate saliency scores
- Active params per token stay at 10B (same 8 experts active)
- Total params drop: 230B → 139B
- Fits in NVFP4 within 128GB; full 230B NVFP4 is borderline
- Claims near-lossless quality on coding/agentic tasks

Model: [cerebras/MiniMax-M2.5-REAP-139B-A10B](https://huggingface.co/cerebras/MiniMax-M2.5-REAP-139B-A10B)

---

## NVFP4 Technical Details

NVFP4 is Blackwell-native hardware — not emulated:

| Format | Bits | Scaling granularity | Hardware |
|---|---|---|---|
| **NVFP4** | 4 (E2M1: 1 sign, 2 exp, 1 mantissa) | FP8 scale per 16-element block + FP32 outer scale | **Blackwell only** (GB10, GB200) |
| FP8 | 8 | Per-tensor/per-channel | Hopper + Blackwell |
| AWQ | 4 (INT4) | Per-group INT scale (group 64–128) | Most GPUs (emulated) |
| GGUF 3-bit | 3 | Mixed per-block | CPU/GPU (llama.cpp) |

Memory reduction: NVFP4 is ~3.5× smaller than FP16, ~1.8× smaller than FP8.

---

## Actual Benchmark Numbers

### Single-user decode (batch size = 1)

| Stack | Decode tok/s | Prefill pp2048 tok/s |
|---|---|---|
| llama.cpp UD-Q3_K_XL | ~26 | ~334 |
| vLLM NVFP4 (base) | ~36–47 | **3,342** |
| vLLM NVFP4 + MTP speculative | ~60–112 | ~3,342 |

> Surprising finding: **at batch=1, llama.cpp is competitive or slightly faster for decode.** NVFP4's advantage is prefill (10× faster) and concurrency.

### Multi-user server mode (NVFP4 + MTP speculative, 1024 in / 1024 out)

| Concurrent users | Aggregate tok/s | Per-user tok/s |
|---|---|---|
| 1 | 60 | 62 |
| 4 | 140 | 37 |
| 8 | 237 | 32 |
| 16 | 341 | 24 |
| 32 | **487** | 17 |
| 64 | **658** | 12 |

The **720 tok/s peak** cited in hardware guides is aggregate high-concurrency throughput — not single-user speed.

### Raw llm-bench numbers (NVFP4 via vLLM, single Spark)

| Test | tok/s |
|---|---|
| Prefill pp2048 | 3,342 ± 142 |
| Decode tg32 (short context) | 16.71 ± 0.24 |
| Prefill at 32K context | 1,519 ± 1 |
| Decode at 32K context | 12.95 ± 0.02 |

### 2× DGX Spark (linked via 200 GbE, RoCE enabled)

| Config | Tok/s |
|---|---|
| TP=2, socket networking | ~22 tok/s |
| TP=2, RoCE enabled | **~42 tok/s** |
| Prefill (GLM-4.6 357B proxy) | ~1,045 tok/s |
| AWQ TP=2, zero context | ~35 tok/s |
| AWQ TP=2, 32K context | ~22 tok/s |
| AWQ TP=2, 100K context | ~12 tok/s |

> The inter-Spark link is **200 GbE Ethernet** (ConnectX-7), NOT NVLink. Socket latency (~200–500 µs) kills performance; enabling RoCE (RDMA) drops it to ~5–10 µs and nearly doubles throughput.

---

## GB10 Hardware Reality Check

| Spec | Value | Caveat |
|---|---|---|
| GPU SMs | 48 | |
| CUDA cores | 6,144 | |
| Peak FP4 (advertised) | ~1 PFLOP (sparse) | |
| Peak FP4 (measured) | ~427 TFLOPS | Sparse matmul, not always achievable |
| Peak FP8 (measured) | ~214 TFLOPS | |
| Peak FP16/BF16 (measured) | ~213 TFLOPS | |
| Peak TF32 | ~53 TFLOPS | |
| Memory | 128 GB LPDDR5X, 8533 MT/s, 256-bit | |
| Memory bandwidth | **273 GB/s** | ← The real bottleneck; H100 SXM = ~3,350 GB/s |
| CPU | 20-core ARM (10× Cortex-X925 + 10× Cortex-A725) | |
| CPU-GPU link | NVLink C2C (internal only) | |
| External networking | Dual 200 Gbps QSFP (ConnectX-7) | Ethernet, not NVLink |
| System TDP | 240W (GB10 die: 140W) | |
| TMEM (Tensor Memory) | **Absent** | Present in datacenter GB200; limits some kernels |
| Instruction set | `mma.sync` | GB200 uses newer `tcgen05`; different performance profile |
| Compute capability | sm_121 / CC 12.1 | |
| Manufacturing | TSMC 3nm | Co-designed with MediaTek |

**273 GB/s memory bandwidth** is the binding constraint for large-model inference. For comparison: H100 SXM has ~3,350 GB/s HBM3e bandwidth — roughly 12× more. This is why single-user decode is ~26–47 tok/s despite impressive TFLOP numbers.

---

## llama.cpp vs NVFP4 vLLM Comparison (same hardware)

| Metric | llama.cpp 3-bit | NVFP4 vLLM | Winner |
|---|---|---|---|
| Prefill pp2048 | ~334 tok/s | ~3,342 tok/s | NVFP4 by 10× |
| Decode tg32 (short context) | ~20 tok/s | ~16–47 tok/s | llama.cpp at bs=1 |
| Decode at long context (32K+) | significantly worse | 12.95 tok/s | NVFP4 |
| Concurrency | single-threaded | excellent (vLLM batching) | NVFP4 |
| Setup complexity | simple | requires vLLM + custom image | llama.cpp |
| Model required | any GGUF | REAP-139B NVFP4 specific | llama.cpp |

---

## Use Case Summary

| Use case | Best config | Realistic tok/s |
|---|---|---|
| Solo developer, interactive | llama.cpp + UD-Q3_K_XL | ~26 tok/s |
| Solo developer, fast responses | NVFP4 vLLM + MTP speculative | ~60–112 tok/s |
| Small team (4–8 users) | NVFP4 vLLM server | 140–237 tok/s aggregate |
| Agentic pipeline (many parallel calls) | NVFP4 vLLM + 32 concurrent | ~487 tok/s aggregate |
| 2× Spark with RoCE | NVFP4 TP=2 | ~42 tok/s single-user |
| High-throughput server (64 users) | NVFP4 vLLM | ~658 tok/s aggregate |

**Bottom line:** The "720 tok/s" is real but only meaningful when running a **multi-user server with 50+ concurrent requests**. For a solo developer the practical number is 26–60 tok/s depending on stack. The machine earns its keep when shared across a team or used for agentic pipelines firing many parallel LLM calls simultaneously.

---

## Pricing & ROI (as of Mar 2026)

- **DGX Spark price**: ~$4,500 USD
- **Power draw**: ~200W system → ~$15/mo electricity at $0.12/kWh continuous
- **Breakeven vs MiniMax API** ($500/month heavy developer use): ~9 months
- After breakeven: marginal cost = electricity only

---

## Key Sources

- [MiniMax 2.5 REAP - NVFP4 on single DGX Spark — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/minimax-2-5-reap-nvfp4-on-single-dgx-spark/361248)
- [Running MiniMax M2.5 Locally on NVIDIA DGX Spark — re:cinq Blog](https://re-cinq.com/blog/minimax-m2-5-nvidia-dgx)
- [NVFP4 BREAKTHROUGH DGX SPARK — Avarok-Cybersecurity/dgx-vllm](https://github.com/Avarok-Cybersecurity/dgx-vllm/blob/main/NVFP4_BREAKTHROUGH_DGX_SPARK.md)
- [We unlocked NVFP4 on the DGX Spark: 20% faster than AWQ! — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/we-unlocked-nvfp4-on-the-dgx-spark-20-faster-than-awq/361163)
- [Can someone with 2 Sparks benchmark NVFP4 MiniMax M2.1 quant?](https://forums.developer.nvidia.com/t/can-someone-with-2-sparks-benchmark-nvfp4-minimax-m2-1-quant/356118)
- [Performance of llama.cpp on NVIDIA DGX Spark — GitHub Discussion #16578](https://github.com/ggml-org/llama.cpp/discussions/16578)
- [Help: Running NVFP4 model on 2x DGX Spark with vLLM + Ray](https://forums.developer.nvidia.com/t/help-running-nvfp4-model-on-2x-dgx-spark-with-vllm-ray-multi-node/353723)
- [Introducing NVFP4 for Efficient and Accurate Low-Precision Inference — NVIDIA Technical Blog](https://developer.nvidia.com/blog/introducing-nvfp4-for-efficient-and-accurate-low-precision-inference/)
- [NVIDIA DGX Spark In-Depth Review — LMSYS Org](https://lmsys.org/blog/2025-10-13-nvidia-dgx-spark/)
- [Is DGX Spark Actually Blackwell? — backend.ai](https://www.backend.ai/blog/2026-02-is-dgx-spark-actually-a-blackwell)
- [cerebras/MiniMax-M2.5-REAP-139B-A10B — HuggingFace](https://huggingface.co/cerebras/MiniMax-M2.5-REAP-139B-A10B)
- [REAP: Router-weighted Expert Activation Pruning — GitHub](https://github.com/CerebrasResearch/reap)
- [New Software and Model Optimizations Supercharge NVIDIA DGX Spark — NVIDIA Technical Blog](https://developer.nvidia.com/blog/new-software-and-model-optimizations-supercharge-nvidia-dgx-spark/)
