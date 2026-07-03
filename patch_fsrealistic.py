#!/usr/bin/env python3
# Stops FSRealistic from resetting the camera when you press F.
#
# The exe checks the F key (VK_F = 0x46) directly in its per-frame camera
# code and forces a zoom reset whenever it's down - ignoring your binds and
# window focus. This flips the one conditional jump that guards that block
# into an unconditional jump, so it never runs. Everything else, including
# the normal configurable reset-camera bind, is untouched.
#
# Offset 0xA59BD:  0F 89 E4 00 00 00  ->  E9 E5 00 00 00 90
#
# Usage: python patch_fsrealistic.py <path to FSRealistic.exe>
# Close FSRealistic first. Original is backed up to FSRealistic.exe.bak.
import struct
import sys
import shutil
from pathlib import Path

TARGET_VA = 0x1400a65bd
ORIGINAL_BYTES = bytes.fromhex("0F89E4000000")
PATCHED_BYTES = bytes.fromhex("E9E500000090")


def va_to_file_offset(data: bytes, va: int) -> int:
    if data[0:2] != b"MZ":
        raise ValueError("Not a valid MZ/PE file")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("Not a valid PE file")

    coff_off = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff_off + 2)[0]
    opt_header_size = struct.unpack_from("<H", data, coff_off + 16)[0]
    opt_header_off = coff_off + 20

    magic = struct.unpack_from("<H", data, opt_header_off)[0]
    if magic == 0x20B:  # PE32+
        image_base = struct.unpack_from("<Q", data, opt_header_off + 24)[0]
    elif magic == 0x10B:  # PE32
        image_base = struct.unpack_from("<I", data, opt_header_off + 28)[0]
    else:
        raise ValueError(f"Unknown optional header magic: {magic:#x}")

    rva = va - image_base
    if rva < 0:
        raise ValueError("VA is below image base")

    section_table_off = opt_header_off + opt_header_size
    for i in range(num_sections):
        sec_off = section_table_off + i * 40
        name = data[sec_off:sec_off + 8].rstrip(b"\x00").decode(errors="replace")
        virtual_size = struct.unpack_from("<I", data, sec_off + 8)[0]
        virtual_addr = struct.unpack_from("<I", data, sec_off + 12)[0]
        raw_size = struct.unpack_from("<I", data, sec_off + 16)[0]
        raw_ptr = struct.unpack_from("<I", data, sec_off + 20)[0]

        span = max(virtual_size, raw_size)
        if virtual_addr <= rva < virtual_addr + span:
            file_off = raw_ptr + (rva - virtual_addr)
            print(f"[i] VA {va:#x} -> RVA {rva:#x} in section '{name}' -> file offset {file_off:#x}")
            return file_off

    raise ValueError(f"RVA {rva:#x} not found in any section")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path to FSRealistic.exe>")
        sys.exit(1)

    exe_path = Path(sys.argv[1])
    if not exe_path.is_file():
        print(f"[!] File not found: {exe_path}")
        sys.exit(1)

    data = bytearray(exe_path.read_bytes())
    file_off = va_to_file_offset(bytes(data), TARGET_VA)

    current = bytes(data[file_off:file_off + len(ORIGINAL_BYTES)])
    if current == PATCHED_BYTES:
        print("[=] Already patched. Nothing to do.")
        return
    if current != ORIGINAL_BYTES:
        print(f"[!] Unexpected bytes at target offset: {current.hex()}")
        print(f"    Expected original: {ORIGINAL_BYTES.hex()}")
        print("    Refusing to patch a build that doesn't match what was analyzed.")
        sys.exit(2)

    backup_path = exe_path.with_suffix(exe_path.suffix + ".bak")
    if not backup_path.exists():
        shutil.copy2(exe_path, backup_path)
        print(f"[i] Backup written to {backup_path}")
    else:
        print(f"[i] Backup already exists at {backup_path} (not overwritten)")

    data[file_off:file_off + len(PATCHED_BYTES)] = PATCHED_BYTES
    exe_path.write_bytes(data)
    print(f"[+] Patched {exe_path}")
    print(f"    {ORIGINAL_BYTES.hex()} -> {PATCHED_BYTES.hex()} at file offset {file_off:#x}")


if __name__ == "__main__":
    main()
