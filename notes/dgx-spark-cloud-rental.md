# DGX Spark (GB10) Cloud Rental Options — Mar 2026

## Summary

**No major cloud provider rents DGX Spark (GB10) hardware.** The machine is a consumer/prosumer device
sold for purchase, not built into any cloud fleet. Options are extremely limited.

---

## Known Rental Options

| Provider | Hardware | Price | Notes |
|---|---|---|---|
| **VFXnow** | DGX Spark (GB10, 128GB) | ~$800/month (~$1.11/hr 24/7) | Only known dedicated DGX Spark rental |
| RunPod | RTX Pro 6000 Blackwell (96GB GDDR7) | ~$0.50/hr | Closest architecture match (SM12x); not identical |
| CoreWeave / Lambda / Vast.ai | No GB10 listed | — | Not available as of Mar 2026 |
| AWS / Azure / GCP | No GB10 listed | — | Not available |
| Modal | No GB10 listed | — | Not available |

---

## Why There's No Cloud Supply

- DGX Spark is a **$4,699 consumer/prosumer device** — clouds build fleets of server-grade H100/B200 nodes
- GB10 is a unique chip co-designed with MediaTek on TSMC 3nm — not procured by hyperscalers
- The unit's 240W TDP and LPDDR5X memory are designed for edge/office use, not rack deployment at scale

---

## NVIDIA DGX Cloud — Shut Down

NVIDIA DGX Cloud (which offered H100/A100 clusters) was shut down / restructured internally in late 2025.
It never offered GB10 hardware anyway.

---

## NVIDIA Brev — NOT a Rental Service

NVIDIA Brev (`brev.nvidia.com`) allows remote access to **hardware you own**. You register your DGX Spark
and access it remotely. It is not a rental marketplace — you must already own the device.

---

## Closest Rentable Blackwell Alternative

### RTX Pro 6000 Blackwell (RunPod)
- **Architecture**: SM12x (same Blackwell family as GB10/GB10B, different from B200's SM100)
- **VRAM**: 96GB GDDR7
- **Price**: ~$0.50/hr on RunPod
- **Suitability for MiniMax M2.5 REAP-139B NVFP4**: Needs verification — 96GB may be sufficient for NVFP4 weights (~69GB)
- **Limitation**: GDDR7 bandwidth (~1.8 TB/s) vs GB10's 273 GB/s — actually **faster** for bandwidth-limited decode

### B200 (CoreWeave / Lambda)
- **Architecture**: SM100 — **different** from GB10's SM12x
- **Price**: $2.69–$6.25/hr depending on provider
- **Suitability**: Yes for large models, but architecture differences mean NVFP4 kernels may behave differently
- **VRAM**: 192GB HBM3e per GPU — can run full 230B MiniMax M2.5

---

## Buy vs Rent Breakeven Analysis

| Scenario | Monthly cost | Breakeven vs purchase ($4,699) |
|---|---|---|
| VFXnow rental | $800/month | **5.9 months** |
| RunPod RTX Pro 6000 (8hr/day) | ~$120/month | ~39 months |
| DGX Spark purchase | $15/month (electricity) | — (own it) |

**Verdict**: If you need DGX Spark for more than 6 months, buying is cheaper than renting via VFXnow.
For short experiments (days to weeks), VFXnow at $800/month is the only true option.
RunPod's RTX Pro 6000 is the pragmatic alternative if you just need a Blackwell SM12x device.

---

## Key Sources

- VFXnow DGX Spark rental: https://vfxnow.com
- RunPod RTX Pro 6000: https://runpod.io
- NVIDIA Brev (own-device remote access): https://brev.nvidia.com
- NVIDIA DGX Cloud status (shut down late 2025): https://www.nvidia.com/en-us/gpu-cloud/
