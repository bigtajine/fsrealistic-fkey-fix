#!/usr/bin/env python3
# Stops FSRealistic from resetting the camera when you press F.
#
# The exe checks the F key (VK_F = 0x46) directly in its per-frame camera
# code and forces a zoom reset whenever it's down - ignoring your binds and
# window focus. The check compiles to roughly:
#
#     MOV  ECX, 0x46          ; VK_F
#     ...
#     CALL [GetKeyState]
#     TEST AX, AX
#     JNS  skip               ; skip the reset only if F isn't down
#     ...reset zoom...
#
# This flips that JNS into an unconditional JMP so the reset block never
# runs. The normal configurable reset-camera bind lives elsewhere and is
# left alone.
#
# Instead of a hardcoded offset (which dies on every new build) this scans
# for the instruction pattern and works out the jump distance itself, so it
# has a decent shot at surviving minor FSRealistic updates. If Sim
# Innovations rewrites how the key is read, it'll safely find nothing rather
# than patch the wrong thing.
#
# Usage: python patch_fsrealistic.py <path to FSRealistic.exe>
# Close FSRealistic first. Original is backed up to FSRealistic.exe.bak.
import re
import sys
import shutil
from pathlib import Path

# MOV ECX, 0x46 (VK_F)  ...  CALL [mem]  ...  TEST AX,AX  JNS rel32
# Wildcards: the MOVAPS/MOVSD/XOR filler between the call and the test can
# shift between compiler versions, so we allow a small gap and only pin the
# instructions that carry the meaning.
MOV_VK_F = b"\xb9\x46\x00\x00\x00"          # MOV ECX, 0x46
CALL_MEM = b"\xff\x15"                       # CALL qword ptr [rip+disp32]
TEST_JNS = re.compile(rb"\x66\x85\xc0\x0f\x89(....)", re.DOTALL)  # TEST AX,AX ; JNS rel32
PATCHED  = re.compile(rb"\x66\x85\xc0\xe9(....)\x90", re.DOTALL)  # TEST AX,AX ; JMP rel32 ; NOP

GAP = 48  # max bytes between the VK_F load and the TEST AX,AX


def find_targets(data: bytes):
    """Return (patch_pos, already_patched) for the F-key guard, or raise."""
    hits = []
    done = []
    for m in re.finditer(re.escape(MOV_VK_F), data):
        window = data[m.end():m.end() + GAP]
        if CALL_MEM not in window:
            continue  # this VK_F load doesn't feed a GetKeyState-style call
        tj = TEST_JNS.search(window)
        if tj:
            # position of the 0F 89 opcode in the file
            hits.append(m.end() + tj.start() + 3)
            continue
        if PATCHED.search(window):
            done.append(m.end())
    return hits, done


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path to FSRealistic.exe>")
        sys.exit(1)

    exe_path = Path(sys.argv[1])
    if not exe_path.is_file():
        print(f"[!] File not found: {exe_path}")
        sys.exit(1)

    data = bytearray(exe_path.read_bytes())
    hits, done = find_targets(bytes(data))

    if not hits and done:
        print("[=] Already patched. Nothing to do.")
        return
    if not hits:
        print("[!] Couldn't find the F-key camera-reset pattern.")
        print("    This build probably reads the key differently - it needs")
        print("    a fresh look in a disassembler before it can be patched.")
        sys.exit(2)
    if len(hits) > 1:
        print(f"[!] Found {len(hits)} matches at {[hex(h) for h in hits]}.")
        print("    Too ambiguous to patch safely; aborting.")
        sys.exit(3)

    pos = hits[0]
    # JNS rel32:  0F 89 <rel32>   (6 bytes)
    # JMP rel32:  E9 <rel32+1> 90 (5 bytes + NOP) -> same target, same length
    rel = int.from_bytes(data[pos + 2:pos + 6], "little")
    new_rel = (rel + 1) & 0xFFFFFFFF
    original = bytes(data[pos:pos + 6])
    patched = b"\xe9" + new_rel.to_bytes(4, "little") + b"\x90"

    print(f"[i] F-key guard (JNS) at file offset {pos:#x}")
    print(f"    {original.hex()} -> {patched.hex()}")

    backup_path = exe_path.with_suffix(exe_path.suffix + ".bak")
    if not backup_path.exists():
        shutil.copy2(exe_path, backup_path)
        print(f"[i] Backup written to {backup_path}")
    else:
        print(f"[i] Backup already exists at {backup_path} (not overwritten)")

    data[pos:pos + 6] = patched
    exe_path.write_bytes(data)
    print(f"[+] Patched {exe_path}")


if __name__ == "__main__":
    main()
