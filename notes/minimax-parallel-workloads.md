# MiniMax M2.5 — Parallel & Multi-User Hardware Configurations (Mar 2026)

> Companion to `128gb-minimax-m2.5.md` and `nvidia-dgx-spark-minimax-analysis.md`.
> Focuses on configurations suited for agentic pipelines, multi-user serving, and parallel workloads.

---

## Why MoE Architecture Changes Everything for Parallelism

MiniMax M2.5 has 256 experts with only 8 active per token (~10B active params out of 230B total). This has profound implications:

- **Expert Parallelism (EP)** is possible: distribute the 256 experts across GPUs so each device owns a subset entirely, rather than sharding each expert across all devices (tensor parallelism)
- **Bandwidth efficiency**: only 10B params worth of weights are read per token — effective bandwidth demand ~43 GB/s at BF16, making even slower memory systems viable
- **MoE beats dense models** on bandwidth-limited hardware: a 70B dense model requires reading all 70B weights per token; MiniMax M2.5 reads ~10B weights per token despite being a 230B model
- **Pipeline parallelism**: NOT supported in vLLM or SGLang for this model family — use TP or EP instead

---

## Official vLLM Parallelism Configs (MiniMax M2.5)

| GPU Count | Config | Command flags | KV Cache capacity |
|---|---|---|---|
| 4× GPU (≥80GB each) | TP=4 | `--tensor-parallel-size 4` | ~400K tokens |
| 8× GPU (≥90GB each) | TP=8 + EP | `--tensor-parallel-size 8 --enable-expert-parallel` | ~3M tokens |
| 8+ GPU (multi-user) | DP+EP | `--data-parallel-size 8 --enable-expert-parallel` | Scales with DP count |

> Pure TP=8 without EP is **not supported** for MiniMax M2 family.

**EP vs TP tradeoff:**
- TP+EP: **52% higher throughput** at low concurrency (64–128 requests) — lower per-request latency
- DP+EP: better at high concurrency — avoids 8× KV cache duplication, scales aggregate throughput
- For solo/small team: TP+EP. For shared server with many users: DP+EP.

Source: [vLLM MiniMax-M2 Usage Guide](https://docs.vllm.ai/projects/recipes/en/latest/MiniMax/MiniMax-M2.html), [AMD ROCm vLLM MoE Playbook](https://rocm.blogs.amd.com/software-tools-optimization/vllm-moe-guide/README.html)

---

## PCIe Bandwidth — The Consumer GPU Cluster Problem

Consumer GPUs connect via PCIe, not NVLink. This creates a hard ceiling on tensor parallelism scaling:

| Config | Throughput | Notes |
|---|---|---|
| 1× RTX 4090 (TP=1) | 2,699 tok/s (small model) | Baseline |
| 2× RTX 4090 PCIe (TP=2) | 1,027 tok/s | **62% LOWER than 1× GPU** |
| H100 SXM NVLink (multi-GPU) | Up to 2.6× over PCIe | NVLink C2C eliminates all-reduce penalty |

**Why:** TP requires all-reduce operations between GPUs after every transformer sub-layer. PCIe Gen4 x16 = 32 GB/s bidirectional; NVLink 3.0 (RTX 3090) = 600 GB/s. For large models that must span multiple GPUs anyway, PCIe is unavoidable but sublinear scaling is guaranteed.

**Practical workaround for consumer multi-GPU:** Use **data parallelism** (multiple independent model instances) rather than tensor parallelism when serving multiple users. Two separate 4× RTX 3090 servers each running one instance will outperform a single 8× RTX 3090 server with TP=8 for multi-user throughput.

Source: [PCIe vs NVLink LLM performance](https://www.glukhov.org/post/2025/06/llm-performance-and-pci-lanes/)

---

## Full Hardware Configuration Table

| Hardware Config | Total Memory | Quantization | Decode tok/s | Prefill tok/s | Cost (hardware) | Power | Inference Stack | Source |
|---|---|---|---|---|---|---|---|---|
| **MiniMax Cloud API** | cloud | native | 50–100 | fast | $0 | — | — | Official |
| **8× RTX PRO 6000 Blackwell** (768 GB VRAM) | 768 GB | FP8 | 70–122 (1–2 users) | — | ~$64,000 | ~5,000W | vLLM + SGLang | [r/LocalLLaMA](https://aihaberleri.org/en/news/minimax-25-ai-model-runs-locally-on-8x-pro-6000-gpus-with-fp8-precision) ✓ |
| **4× H100 80GB SXM** (320 GB VRAM) | 320 GB | FP8 | ~50–80 est. | — | ~$140K new / ~$38–56K used | ~3,500W | vLLM TP=4 | [vLLM docs](https://docs.vllm.ai/projects/recipes/en/latest/MiniMax/MiniMax-M2.html) — ref config |
| **NVIDIA DGX Spark** (single, 128 GB) | 128 GB unified | NVFP4 REAP-139B | **720 peak / 26 single-user** | 3,342 | ~$4,500 | ~200W | vLLM / llama.cpp | [re:cinq](https://re-cinq.com/blog/minimax-m2-5-nvidia-dgx) ✓ |
| **2× DGX Spark + M3 Ultra Mac Studio** (heterogeneous) | 128+128+512 GB | mixed | **2.8× over Mac alone** | — | ~$9,000 + ~$14,099 Mac | ~650W | EXO Labs disaggregated | [EXO blog](https://blog.exolabs.net/nvidia-dgx-spark/) ✓ |
| **2× DGX Spark** (RoCE linked) | 256 GB | NVFP4 TP=2 | ~42 | ~1,045 | ~$9,000 | ~400W | vLLM TP=2 + RoCE | [NVIDIA forums](https://forums.developer.nvidia.com/t/help-running-nvfp4-model-on-2x-dgx-spark-with-vllm-ray-multi-node/353723) ✓ |
| **Mac Studio M4 Max 128GB** | 128 GB unified | UD-Q3_K_XL | ~20–25 | — | ~$3,999 | ~180W | llama.cpp Metal | [Unsloth](https://unsloth.ai/docs/models/minimax-m25) ⚠ |
| **Mac Studio M3 Ultra 192GB** | 192 GB unified | 3-bit / Q5 | ~20–25 | — | ~$5,499 | ~200W | LM Studio / llama.cpp | [Unsloth](https://unsloth.ai/docs/models/minimax-m25) ⚠ |
| **Mac Studio M3 Ultra 512GB** | 512 GB unified | Q8_0 | ~10+ | — | ~$14,099 | ~250W | Ollama | Community ⚠ |
| **AMD MI300X** (1× card, 192 GB HBM3) | 192 GB | BF16 (FP8 bug active) | ~80–100 est. | — | ~$10–15K | ~700W | vLLM | ⚠ FP8 bug [#31475](https://github.com/vllm-project/vllm/issues/31475) |
| **8× RTX 3090** (192 GB VRAM) | 192 GB | BF16-INT4-AWQ | ~15–25 est. | — | ~$5–8K used | ~2,000W | vLLM TP8+EP | [HF discussion](https://huggingface.co/QuantTrio/MiniMax-M2-AWQ/discussions/3) ⚠ |
| **4× RTX A6000 Ada** (192 GB VRAM) | 192 GB | BF16-INT4-AWQ | ~25–40 est. | — | ~$16–20K | ~1,200W | vLLM / SGLang | ⚠ extrapolated |
| **8× RTX A6000 Ada** (384 GB VRAM) | 384 GB | FP8 / BF16 | ~50–80 est. | — | ~$36–51K total | ~2,400W | vLLM TP8+EP | ⚠ extrapolated |
| **KTransformers: RTX 4090 + dual EPYC + 512GB DDR5** | 512 GB RAM + 24 GB VRAM | mixed (252 experts on CPU) | ~8–18 | 4.5× vs llama.cpp | ~$10–20K | ~800W | KTransformers + SGLang | [KTransformers docs](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md) ⚠ |
| **2× Strix Halo (AMD) 256GB cluster** | 256 GB unified | Q6_K_XL | **~17** (MiniMax M2 456B!) | — | ~$4,000 | ~300W | llama.cpp RPC | [Framework Community](https://community.frame.work/t/building-a-two-node-amd-strix-halo-cluster-for-llms-with-llama-cpp-rpc-minimax-m2-glm-4-6/77583) ✓ |
| **1× Strix Halo (AMD) 128GB** | 128 GB unified | UD-Q3_K_XL | ~10–15 est. | — | ~$1,999 | ~120W | llama.cpp Vulkan/ROCm | ⚠ extrapolated from M2 results |
| **4× Strix Halo cluster (512GB)** | 512 GB | Q6_K | ~0.7 (dense 405B) → better on MoE | — | ~$8,000 | ~600W | llama.cpp RPC | [Geerling blog](https://www.jeffgeerling.com/blog/2025/i-clustered-four-framework-mainboards-test-huge-llms/) ✓ |
| **RTX 4090D ×1** (48GB, China variant) | 48 GB VRAM + CPU RAM | Q4_K_M partial offload | ~16–20 | ~67 | ~$5,000 | ~500W | llama.cpp | [HF discussion](https://huggingface.co/unsloth/MiniMax-M2.1-GGUF/discussions/2) ✓ |
| **CPU + 192GB DDR5 + RTX 2080 Ti** (11GB) | 11 GB VRAM + 192 GB RAM | Q4_K_M | ~2–3 | — | ~$3–4K | ~400W | llama.cpp (CPU-bottlenecked) | [llama.cpp #19069](https://github.com/ggml-org/llama.cpp/discussions/19069) ✓ |
| **CPU only** | 96 GB RAM | IQ1_S (47 GB) | ~2.8 | — | ~$1–2K | ~150W | llama.cpp | [SonuSahani](https://sonusahani.com/blogs/minimax-m21-local) ✓ — degraded quality |

> ✓ = community-verified / ⚠ = estimate or extrapolated

---

## AMD Strix Halo Deep Dive

### Hardware Specs (Ryzen AI Max+ 395)

| Spec | Value |
|---|---|
| CPU | 16-core Zen 5 (10 perf + 6 efficiency), 32 threads, up to 5.1 GHz |
| iGPU | Radeon 8060S — **40 CU RDNA 3.5** |
| GPU peak FP16 | ~59.4 TFLOPS |
| Memory | Up to 128 GB LPDDR5X-8000, 256-bit |
| Memory bandwidth | **~215 GB/s** measured (vs Mac M4 Max 128GB: ~546 GB/s) |
| Max GPU VRAM (VGM) | 96 GB (BIOS setting on 128 GB system) |
| TDP | 45–120 W configurable (nominal 55 W) |

### Key Point: MoE bandwidth math

MiniMax M2.5 with 10B active params at BF16 = ~20 GB of weights read per token. At 215 GB/s: theoretical ceiling ~10 tok/s pure decode. But KV cache, embeddings, and other overhead reduce this further. The 17 tok/s result on the MiniMax M2 (456B, 45B active) two-node cluster is better than expected, suggesting good MoE efficiency in llama.cpp.

### Available Systems (128 GB)

| Product | Type | Price |
|---|---|---|
| Framework Desktop | Mini PC / DIY | ~$1,999 |
| GMKtec EVO-X2 | Mini PC | ~$1,999 |
| Corsair AI Workstation 300 | Mini PC | varies |
| HP ZBook Ultra 14 G1a | Laptop | ~$3,950 (128GB/2TB) |
| Minisforum MS-S1 MAX | Mini PC | available |
| 37+ other mini PCs | Various | ~$1,500–2,500 |

### Cluster Configurations

| Config | Total RAM | Notable Result | Cost | Source |
|---|---|---|---|---|
| 1× node 128 GB | 128 GB | ~10–15 tok/s MiniMax M2.5 (est.) | ~$2,000 | extrapolated |
| **2× node 256 GB** | 256 GB | **17 tok/s MiniMax M2 (456B, Q6_K_XL)** | ~$4,000 | [Framework Community](https://community.frame.work/t/building-a-two-node-amd-strix-halo-cluster-for-llms-with-llama-cpp-rpc-minimax-m2-glm-4-6/77583) ✓ |
| 2× node 256 GB | 256 GB | 7–8 tok/s GLM 4.6 (Q4_K_XL) | ~$4,000 | same ✓ |
| 4× node 512 GB (Geerling) | 512 GB | 0.7 tok/s Llama 405B dense (network-bottlenecked) | ~$8,004 | [Geerling](https://www.jeffgeerling.com/blog/2025/i-clustered-four-framework-mainboards-test-huge-llms/) ✓ |
| **4× node AMD official demo** | ~512 GB | Ran Kimi K2.5 (1 trillion param MoE) | ~$8,004 | [AMD dev blog](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-run-a-one-trillion-parameter-llm-locally-an-amd.html) ✓ |

> **Note:** The 4-node Llama 405B result (0.7 tok/s) is for a **dense** 405B model — the RPC network bottleneck is severe for dense models. MoE models like MiniMax M2.5 should perform significantly better on the same hardware because expert parallelism is more network-friendly (bursty vs continuous all-reduce).

### Strix Halo vs Mac Studio M4 Max 128GB

| Metric | Strix Halo 128GB | Mac Studio M4 Max 128GB |
|---|---|---|
| Memory bandwidth | ~215 GB/s | **~546 GB/s** |
| GPU compute FP16 | **~59 TFLOPS** | ~27 TFLOPS |
| 70B dense model | ~5 tok/s | **~8–10 tok/s** |
| MoE models (M2.5) | ~10–15 tok/s (est.) | ~20–25 tok/s (est.) |
| Small models (7–8B) | ~46–52 tok/s | ~50–80 tok/s (MLX) |
| Price (128 GB) | **~$1,999** | ~$3,999 |
| Clustering | Easy (Ethernet RPC) | Harder (Thunderbolt/RPC) |
| Software ecosystem | ROCm/Vulkan (rough edges) | Metal/MLX (mature) |
| Linux native | **Yes** | No (macOS only) |

**Verdict:** For pure LLM token throughput, Mac M4 Max wins due to 2.5× bandwidth advantage. For price-per-GB-of-memory, Strix Halo wins at 2×. For clustering flexibility and open ecosystem, Strix Halo wins. For MoE models specifically (active params vs total params), the gap narrows considerably.

---

## EXO Labs: Disaggregated Prefill + Decode (Heterogeneous Cluster)

A key insight for parallel workloads: **prefill and decode have different hardware requirements.**

| Phase | Compute profile | Best hardware |
|---|---|---|
| **Prefill** (processing input tokens) | Compute-bound (TFLOPS) | NVIDIA Blackwell (NVFP4), H100 |
| **Decode** (generating output tokens) | Memory bandwidth-bound | Apple Silicon, HBM systems |

EXO Labs demonstrated this in practice:
- **2× DGX Spark** (Blackwell, high compute) handle prefill
- **M3 Ultra Mac Studio** (512 GB, 800 GB/s bandwidth) handles decode
- Result: **2.8× throughput vs Mac alone**
- Architecture: [EXO 1.0 disaggregated inference](https://blog.exolabs.net/nvidia-dgx-spark/)

This is the "best of both worlds" approach — use cheap bandwidth-optimized hardware for token generation, and burst on compute-optimized hardware for prompt processing. For agentic pipelines with long system prompts (high prefill load), this architecture is very effective.

---

## KTransformers: Expert Offload to CPU RAM

For setups where VRAM is limited but CPU RAM is large:

```bash
python -m sglang.launch_server \
  --model MiniMaxAI/MiniMax-M2.5 \
  --kt-cpuinfer 252 \       # 252 of 256 experts on CPU
  --kt-num-gpu-experts 4 \  # 4 hottest experts stay on GPU
  --kt-method FP8
```

| Hardware | CPU RAM | GPU VRAM | Reported speedup vs llama.cpp |
|---|---|---|---|
| 2× RTX 5090 + EPYC | 256+ GB | 64 GB | 4.5× prefill, 1.25–4× decode |
| RTX 4090 + dual Xeon | 512 GB | 24 GB | similar range |

KTransformers uses **AMX-optimized FP8 kernels** for CPU expert compute and **asynchronous scheduling** so GPU attention and CPU expert computation overlap. NUMA-aware TP provides up to 63% additional decode throughput on dual-socket servers.

Source: [KTransformers MiniMax-M2.5 guide](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md)

---

## Multi-Token Prediction (MTP) — Built-in Speculative Decoding

MiniMax M2.5 includes **3 MTP (Multi-Token Prediction) heads** built into the architecture (per config.json, confirmed by first agent). These enable speculative decoding without a separate draft model.

| Implementation | Speedup | Context |
|---|---|---|
| NVFP4 + MTP on DGX Spark | up to 2.75× single-request | From Avarok/DGX Spark benchmark |
| MTP on similar MoE (Qwen3.5-122B, 8× RTX PRO 6000) | **2.75× single-request** | [SGLang issue #19603](https://github.com/sgl-project/sglang/issues/19603) ✓ |
| vLLM + MTP speculative | 60–112 tok/s (vs 36–47 base) | DGX Spark single user |

MTP is most effective for:
- **Agentic tool-call patterns** where next tokens are predictable (JSON structure, code boilerplate)
- Short output lengths with repetitive structure
- Less effective for creative/open-ended generation

---

## SGLang RadixAttention — KV Cache Sharing for Agentic Workflows

For agentic workloads with shared system prompts or repeated context:

- RadixAttention uses a radix tree as an LRU KV cache, enabling automatic reuse across requests
- Up to **6.4× higher throughput** vs baseline systems on agent/few-shot workloads
- Particularly valuable when many parallel agent calls share the same system prompt or tool definitions

**Combined with MiniMax M2.5:** A team of agents using the same base context (shared tool definitions, codebase context) can reuse KV cache across all parallel calls, dramatically reducing prefill cost. This is a major multiplier for agentic pipelines.

Source: [SGLang LMSYS blog](https://lmsys.org/blog/2024-01-17-sglang/)

---

## Parallelism Strategy Guide by Use Case

| Use Case | Recommended Config | Key Setting |
|---|---|---|
| Solo developer, interactive | Single node, llama.cpp | N/A |
| Solo developer, faster responses | Single node, NVFP4 + MTP | vLLM + speculative |
| 2–5 users sharing one server | TP+EP | `--tensor-parallel-size N --enable-expert-parallel` |
| Many parallel agent calls (same system prompt) | SGLang + RadixAttention | KV cache sharing |
| High concurrency, many users | DP+EP | `--data-parallel-size N --enable-expert-parallel` |
| Long prompts / agentic pipeline | Disaggregated prefill+decode | EXO / Mooncake architecture |
| Budget multi-node cluster | Strix Halo RPC | llama.cpp --rpc |
| CPU-heavy server, limited VRAM | KTransformers expert offload | `--kt-cpuinfer 252` |
| Max throughput per dollar | Multiple independent instances (DP) | No TP overhead |

---

## Budget-Tiered Summary for Parallel Workloads

| Budget | Config | Decode tok/s (agentic) | Notes |
|---|---|---|---|
| **~$2,000** | 1× Strix Halo 128GB | ~10–15 | Best price/GB; open ecosystem |
| **~$4,000** | 2× Strix Halo 256GB | **~17–25** | Confirmed MiniMax M2 17 tok/s |
| **~$4,500** | 1× DGX Spark (NVFP4 server) | **487+ tok/s aggregate (32 users)** | Best bang/buck for agentic throughput |
| **~$4,000** | Mac Studio M4 Max 128GB | ~20–25 single | Mature ecosystem, silent |
| **~$5,500** | Mac Studio M3 Ultra 192GB | ~20–25 | More headroom |
| **~$8,000** | 4× Strix Halo 512GB | >17 tok/s on M2.5 MoE (est.) | Runs 1T-param MoE per AMD demo |
| **~$9,000** | 2× DGX Spark (RoCE) | ~42 single / 658 aggregate (64 users) | Best local server option |
| **~$10K–20K** | KTransformers: RTX 4090 + EPYC + 512GB DDR5 | ~8–18 + 4.5× prefill | Expert offload, agentic-friendly |
| **~$20K** | 4× RTX A6000 Ada 48GB | ~25–40 | NVLink pairs, no FP8 |
| **~$23,500** | 2× DGX Spark + M3 Ultra Mac | **2.8× over Mac alone** | EXO disaggregated architecture |
| **~$64,000** | 8× RTX PRO 6000 (768GB) | 70–122 tok/s (FP8 vLLM) | Full FP8 precision |

---

## Key Takeaways

1. **For agentic pipelines with many parallel calls**: DGX Spark NVFP4 in server mode is the current best-value option at $4,500 — 487+ tok/s aggregate at 32 concurrent users.

2. **For budget multi-node**: 2× Strix Halo ($4,000) outperforms 1× Mac Studio M4 Max ($4,000) for large MoE models while enabling 256 GB total memory.

3. **PCIe consumer GPU clusters**: Useful for holding the model in VRAM, but TP scaling is sublinear. Use data parallelism (multiple instances) not tensor parallelism for multi-user throughput.

4. **Disaggregated prefill/decode** (EXO pattern): Run Sparks for prefill, Mac/high-bandwidth hardware for decode. 2.8× over Mac alone for ~2× the cost.

5. **MTP speculative decoding**: Up to 2.75× speedup for agentic/structured output patterns — essentially free throughput boost when using vLLM or SGLang with MiniMax M2.5's built-in MTP heads.

6. **SGLang RadixAttention**: Up to 6.4× throughput improvement for workloads with shared prefixes (multi-agent with shared system prompt, few-shot examples, codebase context).

7. **AMD Strix Halo caveat**: ROCm/Vulkan still has rough edges (gfx1151 HIP bugs, ROCm 7.0.2 crashes on some configs). The Vulkan backend + AMDVLK is most stable; build llama.cpp with `-DGGML_HIP_ROCWMMA_FATTN=ON -DAMDGPU_TARGETS="gfx1151"` for best HIP performance.

---

## Sources

- [vLLM MiniMax-M2 Series Usage Guide](https://docs.vllm.ai/projects/recipes/en/latest/MiniMax/MiniMax-M2.html)
- [vLLM Expert Parallel Deployment](https://docs.vllm.ai/en/latest/serving/expert_parallel_deployment/)
- [AMD ROCm vLLM MoE Playbook](https://rocm.blogs.amd.com/software-tools-optimization/vllm-moe-guide/README.html)
- [EXO Labs: DGX Spark + M3 Ultra disaggregated inference](https://blog.exolabs.net/nvidia-dgx-spark/)
- [Tom's Hardware: EXO Labs 2.8× result](https://www.tomshardware.com/software/two-nvidia-dgx-spark-systems-combined-with-m3-ultra-mac-studio-to-create-blistering-llm-system-exo-labs-demonstrates-disaggregated-ai-inference-and-achieves-a-2-8-benchmark-boost)
- [Framework Community: Two-node Strix Halo cluster for MiniMax M2](https://community.frame.work/t/building-a-two-node-amd-strix-halo-cluster-for-llms-with-llama-cpp-rpc-minimax-m2-glm-4-6/77583)
- [Jeff Geerling: Four-node Framework cluster](https://www.jeffgeerling.com/blog/2025/i-clustered-four-framework-mainboards-test-huge-llms/)
- [AMD Developer: Trillion-parameter LLM on Ryzen AI Max+ cluster](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-run-a-one-trillion-parameter-llm-locally-an-amd.html)
- [KTransformers MiniMax-M2.5 Guide](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/MiniMax-M2.5.md)
- [PCIe vs NVLink LLM performance](https://www.glukhov.org/post/2025/06/llm-performance-and-pci-lanes/)
- [llama.cpp HIP/ROCm issue #13565 (Strix Halo)](https://github.com/ggml-org/llama.cpp/issues/13565)
- [AMD Strix Halo Toolboxes (kyuz0)](https://github.com/kyuz0/amd-strix-halo-toolboxes)
- [mratsim BF16-INT4-AWQ hybrid quant](https://huggingface.co/mratsim/MiniMax-M2.5-BF16-INT4-AWQ)
- [vLLM MI300X FP8 bug #31475](https://github.com/vllm-project/vllm/issues/31475)
- [SGLang RadixAttention](https://lmsys.org/blog/2024-01-17-sglang/)
- [NVIDIA DGX Spark + NVFP4 forum thread](https://forums.developer.nvidia.com/t/minimax-2-5-reap-nvfp4-on-single-dgx-spark/361248)
- [MiniMax M2.5 vLLM deploy guide](https://github.com/MiniMax-AI/MiniMax-M2.5/blob/main/docs/vllm_deploy_guide.md)
- [QuantTrio/MiniMax-M2-AWQ 8×3090 discussion](https://huggingface.co/QuantTrio/MiniMax-M2-AWQ/discussions/3)
- [llama.cpp DGX Spark discussion #16578](https://github.com/ggml-org/llama.cpp/discussions/16578)
- [llm-tracker.info Strix Halo GPU performance](https://llm-tracker.info/AMD-Strix-Halo-(Ryzen-AI-Max+-395)-GPU-Performance)
