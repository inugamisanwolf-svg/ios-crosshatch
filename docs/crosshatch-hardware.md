# Pixel 3 XL (crosshatch) — hardware mapping for the iOS port

Source: live device tree pulled from the device (`adb pull /sys/firmware/fdt`),
decompiled with pyfdt. All values below are **[実測]** from that live DTB unless
marked otherwise. Cross-referenced against the mainline Linux `sdm845.dtsi` /
`sdm845-google-common.dtsi` / `sdm845-google-crosshatch.dts` **[文献]**.

## Board identity

| Field | Value |
|---|---|
| Model | Google Inc. MSM sdm845 C1 DVT1.1 |
| compatible | `google,b1c1-sdm845`, `qcom,sdm845` |
| qcom,msm-id | 321 (SDM845) |
| SoC | Snapdragon 845 (SDM845, 10 nm) |
| Bootloader | unlocked (`flash.locked=0`, `verifiedbootstate=orange`) |

## The good news: almost every SoC base address matches flame (SD855)

The SD845 and SD855 share the same Qualcomm SoC layout. These addresses are
**identical** to what ios-flame (Pixel 4) already uses, so the flame drivers
carry over with little or no change:

| Block | crosshatch (SD845) [実測] | flame (SD855) |
|---|---|---|
| GIC | GICv3: GICD `0x17a00000`, GICR `0x17a60000` (stride 0x20000) | same |
| Timer | 19.2 MHz, vtimer INTID 19 (PPI 3) | same |
| UFS | `ufshc@0x1d84000` (size 0x2500), `qcom,ufshc` | same |
| USB | DWC3 `@0xa600000` (`qcom,dwc-usb3-msm`) | same |
| Wi-Fi | WCN3990 (`qcom,icnss@0x18800000`) | same |
| SPMI | `@0xc440000` | same |
| SMEM | `@0x86000000` | same |

## What differs (the actual porting work)

| Block | crosshatch (SD845) | flame (SD855) | Impact |
|---|---|---|---|
| **PMIC** | PM8998 (+ PMI8998) | PM8150 | keys (PON), touch rails, battery, RTC drivers |
| **Touch** | Synaptics S6SY761, I2C @0x48 on QUP SE2 (`i2c@0x888000`) | ST FTS ftm5 over SPI @0x890000 | **new touch driver needed** |
| **Panel** | Samsung SW43402 cmd-mode DSC, 1440×2960 | NT37280 cmd, 1080×2280 | display timings, framebuffer |
| **RAM** | 4 GB, single bank | 6 GB, two banks | memory map |
| **CPU** | 4× A75 (gold) + 4× A55 (silver), MPIDR Aff1 | 4× A55 + 4× A76 | core bring-up (both ARMv8.2, 16 KB pages OK) |

## Memory map [実測]

- `memory` reg = `<0 0x80000000 0 0xfe0a0000>` — **single 4 GB bank at 0x80000000**,
  ~3.97 GiB usable. No upper bank above 4 GB (unlike sweet/flame which use highmem).
- `cont_splash_region@0x9d400000` — ABL splash framebuffer (1440×2960×4 BGRA ≈ 16.3 MiB).
- `hyp_region@0x85700000` — hypervisor carve-out.
- SMEM @`0x86000000`.

## Touch [実測]

```
touchscreen@48 {
  compatible = "sec,sec_ts";          // Synaptics S6SY761
  reg = <0x48>;                        // I2C addr 0x48, QUP SE2 (i2c@0x888000)
  sec,irq_gpio    = <tlmm 125>;
  sec,reset_gpio  = <tlmm 99>;
  sec,firmware_name = "s6sy761.fw";
  sec,regulator_dvdd = "pm8998_l14";   // 1.8 V
  sec,regulator_avdd = "pm8998_l19";   // 3.3 V
  sec,max_coords = <1440 2960>;
}
```

## Display [実測]

- Panel: `SW43402 cmd mode dsc dsi panel` (Samsung), 1440×2960.
- Splash framebuffer at `0x9d400000` (a8r8g8b8, stride 1440×4).

## To do before the first `fastboot boot`

1. Build the baseline kernel (flame 0001-0124) on CI — in progress.
2. Port the flame patch set to crosshatch: update the `mkadt.py` constants
   (GIC/UFS/USB/Wi-Fi already match; memory map, PMIC, touch, panel differ).
3. New Synaptics S6SY761 I2C touch driver (flame's is ST FTS over SPI; sweet's is
   Goodix I2C — neither matches).
4. PM8998 key/touch-rail/battery addresses (flame uses PM8150).
5. SW43402 panel timings + the `0x9d400000` splash address.
