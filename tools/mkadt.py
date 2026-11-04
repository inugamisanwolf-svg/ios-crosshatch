#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the SWEET xnu needs to boot on crosshatch.

Pixel 3 XL (crosshatch, SDM845). Forked from ios-flame's mkadt.py; the flame
(Pixel 4, SM8150) values are kept in comments where they differ. Every MMIO
address comes from the crosshatch live FDT. The kernel's built-in drivers still
match the Redmi names (xiaomi,sweet, qcom,kryo470, sweet,display), so those stay.
Usage:  mkadt.py OUT.adt [--dump] [--qemu]
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# Kernel-managed RAM. crosshatch has a single 4 GB bank (0x80000000..0x180000000),
# no above-4G highmem. The live FDT reserved-memory carve-outs are:
#   hyp 0x85700000, xbl 0x85e00000, removed 0x85fc0000, qseecom 0x8ab00000,
#   camera 0x8bf00000, adsp 0x8c500000, wlan_fw 0x8df00000, modem 0x8e000000
#   (0x9800000), video 0x97800000, cdsp 0x97d00000, mba 0x98500000,
#   slpi 0x98700000, spss 0x99b00000, cont_splash 0x9d400000,
#   debug_info 0xa1800000, ramoops 0xa1810000 / alt 0xa1a10000 / meta 0xa1c10000,
#   rmtfs 0xf2700000.
# We take the large free gap between the ramoops region and rmtfs.
# [推測] refine during first XNU bring-up from the panic/console log.
PHYS_BASE = 0xa2000000
MEM_SIZE = 0x50700000
# (flame low: PHYS_BASE 0xb0000000, MEM_SIZE 0x4d000000; flame highmem below 4G
#  was HIGH_PHYS_BASE 0x100000000 / HIGH_MEM_SIZE 0xfcc00000 — crosshatch has none.)
SOC_BASE = 0x01000000

# Identical to flame (SD855): GICv3, UFS, timer all at the same addresses.
GICD, GICD_SIZE = 0x17a00000, 0x10000
GICR, GICR_SIZE = 0x17a60000, 0x100000
# cont_splash_region@9d400000; ABL scans it out (cmd-mode panel).
FB, FB_SIZE = 0x9d400000, 0x2400000
SWEET_ECID = 0x5357454554000001  # 'SWEET' + 1, synthetic
FB_W, FB_H, FB_STRIDE = 1440, 2960, 1440 * 4
# Internal UFS host (ufshc@1d84000 "ufs_mem"); same as flame.
UFS, UFS_SIZE = 0x01d84000, 0x3000
TIMEBASE = 19200000
VTIMER_INTID = 19
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

BOOT_MANIFEST_HASH = hashlib.sha384(b'sweet boot manifest').digest()

D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """(/product properties of the real D22AP tree — see ios-flame's mkadt.py.)"""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')


u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'

PANIC_LOG_PA = 0x1fd000000
PANIC_LOG_SIZE = 0x80000


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(seed=None, qemu=False):
    phys_base, mem_size = PHYS_BASE, MEM_SIZE
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu else (GICD, GICR, TIMEBASE)
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('crosshatch-shim')),
        ('system-firmware-version', cstr('crosshatch-shim')),
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        ('crypto-hash-method', cstr('sha2-384')),
        ('display-scale', u32(3)),
        ('unique-chip-id', struct.pack('<Q', SWEET_ECID)),
        ('chip-id', u32(0x8015)),
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
        ('mac-address-wifi0', bytes([0x02, 0x50, 0x49, 0x58, 0x45, 0x4c])),
        ('mac-address-bluetooth0', bytes([0x02, 0x50, 0x49, 0x58, 0x45, 0x4d])),
        ('mac-address-ethernet0', bytes([0x02, 0x50, 0x49, 0x58, 0x45, 0x4e])),
        ('embedded-panic-log-size', u32(PANIC_LOG_SIZE)),
    ], [node('memory-map', [ph()]),
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # SMP: 8 cores, MPIDR Aff1 encoding. crosshatch Kryo 385: 4x A55 silver
    # (cpu0-3, ~1.77 GHz) + 4x A75 gold (cpu4-7, ~2.80 GHz). Same homogeneous
    # cluster layout as flame.
    cpu_nodes = []
    for core in range(1 if qemu else 8):
        cpu_nodes.append(node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('qcom,kryo470') + cstr('qcom,kryo385') + cstr('ARM,v8')),
            ('reg', u32(core << 8)),
            ('cpu-id', u32(core)),
            ('cluster-id', u32(0)),
            ('cluster-type', u32(0)),
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(core)),
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if core == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            ('clock-frequency', u32(2803200000 if core >= 4 else 1766400000)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', u64(gicd - SOC_BASE, GICD_SIZE, gicr - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        node('wlan', [
            ph(),
            ('device_type', cstr('wlan')),
            ('compatible', cstr('flame,wcn3990')),
        ]),
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('sweet,display')),
            ('canvas-width', u32(1125)),
            ('canvas-height', u32(2436)),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    pram = node('pram', [ph(), ('reg', struct.pack('<2Q', PANIC_LOG_PA, PANIC_LOG_SIZE))])

    ufs = node('sweet-ufs', [
        ph(),
        ('compatible', cstr('qcom,ufshc')),
        ('reg', u64(UFS, UFS_SIZE)),
    ])

    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    product = [node('product', [ph()] + product_props)] if product_props else []

    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,sweet') + cstr('google,crosshatch') + cstr('qcom,sdm845') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons] + product + ([] if qemu else [ufs, pram]))


if __name__ == '__main__':
    root = build(qemu='--qemu' in sys.argv)
    blob = adt.serialize(root)
    open(sys.argv[1], 'wb').write(blob)
    if '--dump' in sys.argv:
        adt.dump(adt.parse(blob)[0])
    print(f'{sys.argv[1]}: {len(blob)} bytes', file=sys.stderr)
