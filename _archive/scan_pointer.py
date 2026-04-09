
import struct, os
from collections import defaultdict

SNAP_DIR = r'c:\Users\james\code\StatsBorg\_archiveesearch\snapshots'
DATA_VA = 0x46D6E0

MID_FILES = ['ctf_data.bin', 'slayer_data.bin', 'oddball_data.bin', 'koth_data.bin']
WAR_FILES = ['assault_data.bin', 'juggernaut_data.bin', 'territories_data.bin']
MID_BASE = 0x568308
WAR_BASE = 0x548308

def scan4(data, target):
    tb = struct.pack('<I', target)
    hits = []
    for off in range(0, len(data)-3, 4):
        if data[off:off+4] == tb:
            hits.append((off, DATA_VA + off))
    return hits

def load(fname):
    with open(os.path.join(SNAP_DIR, fname), 'rb') as f:
        return f.read()

def main():
    S = '=' * 80
    print(S)
    print('POINTER SCANNER: Fixed pointers to dynamic map info structure')
    print(S)
    print(f'
.data VA base: 0x{DATA_VA:08X}')
    print(f'Midship base: 0x{MID_BASE:08X}  map name: 0x{MID_BASE+0x178:08X}')
    print(f'Warlock base: 0x{WAR_BASE:08X}  map name: 0x{WAR_BASE+0x178:08X}')

    ad = {}
    for fn in MID_FILES + WAR_FILES:
        ad[fn] = load(fn)
        print(f'  Loaded {fn}: {len(ad[fn])} bytes')

    groups = [
        ('MIDSHIP', MID_FILES, MID_BASE),
        ('WARLOCK', WAR_FILES, WAR_BASE),
    ]

    consistent_per_group = {}

    for gn, files, base in groups:
        mn = base + 0x178
        print(f'
{S}')
        print(f'{gn} -- base: 0x{base:08X}')
        print(S)
        for label, tgt in [('base', base), ('map name', mn)]:
            print(f'
  {label} pointer (0x{tgt:08X}):')
            va2f = defaultdict(set)
            for fn in files:
                hits = scan4(ad[fn], tgt)
                if hits:
                    print(f'    {fn}: {len(hits)} hit(s)')
                    for fo, va in hits:
                        print(f'      offset 0x{fo:06X} => VA 0x{va:08X}')
                        va2f[va].add(fn)
                else:
                    print(f'    {fn}: no hits')
            cons = {va for va, fs in va2f.items() if len(fs) == len(files)}
            if cons:
                print(f'  CONSISTENT in all {len(files)} files:')
                for va in sorted(cons):
                    print(f'    VA 0x{va:08X} (offset 0x{va-DATA_VA:06X})')
            key = f'{gn}_{label}'
            consistent_per_group[key] = cons

    # Cross-ref base
    print(f'
{S}')
    print('CROSS-REFERENCE: Same VA for base pointer in BOTH groups')
    print(S)
    mb = consistent_per_group.get('MIDSHIP_base', set())
    wb = consistent_per_group.get('WARLOCK_base', set())
    common = mb & wb
    if common:
        for va in sorted(common):
            print(f'  VA 0x{va:08X}: Midship->0x{MID_BASE:08X}, Warlock->0x{WAR_BASE:08X}')
    else:
        print('  No common base pointer VA.')
        if mb: print(f'  Midship-only: {sorted([hex(v) for v in mb])}')
        if wb: print(f'  Warlock-only: {sorted([hex(v) for v in wb])}')

    # Cross-ref map name
    mm = consistent_per_group.get('MIDSHIP_map name', set())
    wm = consistent_per_group.get('WARLOCK_map name', set())
    cmn = mm & wm
    if cmn:
        print(f'
  MAP NAME PTR same VA in both:')
        for va in sorted(cmn):
            print(f'    VA 0x{va:08X}')
    else:
        print('
  No common map name pointer VA.')
        if mm: print(f'  Midship-only: {sorted([hex(v) for v in mm])}')
        if wm: print(f'  Warlock-only: {sorted([hex(v) for v in wm])}')

    # Broader: any ptr into base..base+0x400
    print(f'
{S}')
    print('BROADER: Any pointer into map info region (base..base+0x400)')
    print(S)
    broad = {}
    for gn, files, base in groups:
        print(f'
  {gn}: 0x{base:08X}..0x{base+0x400:08X}')
        pf = {}
        for fn in files:
            d = ad[fn]
            found = {}
            for off in range(0, len(d)-3, 4):
                v = struct.unpack_from('<I', d, off)[0]
                if base <= v < base + 0x400:
                    found[DATA_VA + off] = v
            pf[fn] = found
        cv = set(pf[files[0]].keys())
        for fn in files[1:]:
            cv &= set(pf[fn].keys())
        broad[gn] = (pf, cv, files, base)
        if cv:
            print(f'    {len(cv)} common VA(s):')
            for va in sorted(cv):
                vals = [pf[f][va] for f in files]
                vs = ', '.join(f'0x{v:08X}' for v in vals)
                offs = [v - base for v in vals]
                if len(set(vals)) == 1:
                    print(f'      VA 0x{va:08X}: [{vs}] (offset +0x{offs[0]:X})')
                else:
                    os2 = ', '.join(f'+0x{o:X}' for o in offs)
                    print(f'      VA 0x{va:08X}: [{vs}] (VARIES: {os2})')
        else:
            print('    No common VAs.')

    # Cross-ref broader
    _, cm2, _, _ = broad['MIDSHIP']
    _, cw2, _, _ = broad['WARLOCK']
    olap = cm2 & cw2
    if olap:
        print(f'
  CROSS-REF BROADER: {len(olap)} VA(s) in both:')
        mpf, _, mf, mbase = broad['MIDSHIP']
        wpf, _, wf, wbase = broad['WARLOCK']
        for va in sorted(olap):
            mv = [mpf[f][va] for f in mf]
            wv = [wpf[f][va] for f in wf]
            mo = [v - mbase for v in mv]
            wo = [v - wbase for v in wv]
            ao = set(mo + wo)
            ms = ', '.join('0x%08X' % v for v in mv)
            ws = ', '.join('0x%08X' % v for v in wv)
            print(f'    VA 0x{va:08X}:')
            print(f'      Midship: [{ms}] offs: {[+0x%X % o for o in mo]}')
            print(f'      Warlock: [{ws}] offs: {[+0x%X % o for o in wo]}')
            if len(ao) == 1:
                print(f'      ** CONSISTENT offset +0x{list(ao)[0]:X} in ALL snapshots!')
    else:
        print('
  No overlap in broader search.')

    # Pointer chains
    print(f'
{S}')
    print('POINTER CHAINS: ptr -> ptr -> base')
    print(S)
    csrc = {}
    for gn, files, base in groups:
        print(f'
  {gn} (using {files[0]}):')
        d = ad[files[0]]
        holders = set()
        for off in range(0, len(d)-3, 4):
            v = struct.unpack_from('<I', d, off)[0]
            if v == base:
                holders.add(DATA_VA + off)
        print(f'    {len(holders)} locations hold 0x{base:08X}')
        chains = []
        for off in range(0, len(d)-3, 4):
            v = struct.unpack_from('<I', d, off)[0]
            if v in holders:
                chains.append((DATA_VA + off, v))
        if chains:
            print(f'    {len(chains)} chain(s):')
            for s, m in chains:
                print(f'      0x{s:08X} -> 0x{m:08X} -> 0x{base:08X}')
        else:
            print('    No chains.')
        csrc[gn] = {s for s, _ in chains}

    cc = csrc.get('MIDSHIP', set()) & csrc.get('WARLOCK', set())
    if cc:
        print(f'
  SAME source VA in both groups:')
        for va in sorted(cc):
            print(f'    VA 0x{va:08X}')
    else:
        print('
  No common chain sources.')

    print('
Done.')

main()
