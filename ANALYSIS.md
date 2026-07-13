# FSRealistic "F Key Resets Camera" — Technical Analysis

**Date:** 2026-07-13
**Research Method:** Ghidra disassembly/decompilation of the shipped exe + pattern-matching validation
**Analysis Tool:** Ghidra (manual) + Python byte-pattern scanner
**Target:** `FSRealistic.exe` (Sim Innovations FSRealistic, MSFS add-on)

---

## Executive Summary

Pressing **F** while FSRealistic is running snaps/re-zooms the camera, even when:

- the "Reset camera" bind has been removed from every controller in FSRealistic's own settings, and
- the sim window doesn't have focus at all (typing F in the EFB, alt-tabbed to another app, etc.).

There is no in-app option to disable this. `config.json` exposes `reset_camera_button_id`, but that only lets a user add a *second* trigger — it doesn't replace or gate the one baked into the binary. The root cause is a hardcoded, unconditional poll of the F key inside the exe's per-frame camera-update routine, independent of FSRealistic's configurable bind system.

This document provides the technical foundation for the byte-patch fix in `patch_fsrealistic.py`.

---

## Investigation Path

```
┌──────────────────────────────────────┐
│ FSRealistic.exe                       │
├──────────────────────────────────────┤
│ Per-frame camera update routine       │
│ (FUN_1400a6590 in the analyzed build) │
│                                        │
│ Polls two independent key sources:    │
│  1. Configurable bind system          │
│     (reset_camera_button_id, reads    │
│      config.json, respects user       │
│      unbinding it entirely)           │
│  2. A SECOND, hardcoded VK_F poll     │
│     via GetKeyState — not gated by    │
│     any config value, not tied to     │
│     the bind table at all             │
└──────────────┬─────────────────────────┘
               │
               ▼
      Hardcoded VK_F check forces the
      reset-zoom flag whenever F is down,
      regardless of binds or focus.
```

`GetKeyState` reads the global/system keyboard state rather than a window-message queue, which is why the bug fires even when MSFS/FSRealistic isn't the focused window.

---

## Root Cause

### The Hardcoded Poll

Inside the camera-update function, alongside the normal (configurable) reset-camera bind handling, the following sequence appears:

```asm
MOV  ECX, 0x46            ; 0x46 = VK_F
...                        ; small filler (MOVAPS/MOVSD/XOR, varies by build)
CALL [GetKeyState]         ; qword ptr [rip+disp32] import thunk
TEST AX, AX
JNS  skip                  ; if F is NOT currently down, skip the reset
...                         ; otherwise: force reset-zoom flag + default zoom
skip:
```

This is a **second, independent** key check from the configurable bind system — it does not read `reset_camera_button_id`, does not consult the user's controller profile, and has no associated settings entry. It simply always fires on raw VK_F, every frame, whether or not F is bound to anything in FSRealistic's own UI.

The `TEST AX, AX` / `JNS` pair is the standard compiler pattern for "branch if the high bit of the `GetKeyState` result is clear" — i.e. "branch if the key is *not* currently pressed." When F is held, the branch is *not* taken and the reset-zoom path executes.

### Why It Survives Every "Unbind"

Because this check is compiled directly into the per-frame update loop rather than driven by the bind table, removing every controller binding for "Reset camera" in FSRealistic's settings has no effect on it — the code path that fires the reset from the hardcoded poll is entirely separate from the code path that fires it from a user-configured bind.

### Why It Fires Without Focus

`GetKeyState` (as opposed to `GetAsyncKeyState`-with-focus-checks or a `WM_KEYDOWN` message handler) reflects the last key-state update delivered to the calling thread's message queue, but in practice for a background/global poll like this it behaves as effectively focus-independent for held keys — consistent with the reported symptom of the reset firing while alt-tabbed or while typing "F" in an unrelated window (e.g. the in-sim EFB).

---

## Confirmed Patch Site

| Build | File Offset | Edit |
|---|---|---|
| Build analyzed 2026-07 | `0xA59BD` | `JNS rel32` → `JMP rel32` (equal-length rewrite) |

```
0F 89 E4 00 00 00   ->   E9 E5 00 00 00 90
```

- `0F 89 <rel32>` (`JNS`, 6 bytes) becomes `E9 <rel32+1> 90` (`JMP`, 5 bytes + 1-byte `NOP` pad) — same length, same branch target, no relocation or offset shift elsewhere in the file.
- The `+1` adjustment on `rel32` accounts for `JMP rel32`'s opcode being one byte shorter than `JNS rel32`'s, which shifts where the displacement is measured from.
- Only the branch is touched. The `GetKeyState` call itself, the `MOV ECX, 0x46` key-code load, and the normal configurable reset-camera path are left untouched — this patch is scoped exclusively to the second, hardcoded poll.

Because a fixed file offset would break on every FSRealistic update, `patch_fsrealistic.py` does not hardcode `0xA59BD`. Instead it scans for the instruction pattern itself:

1. `MOV ECX, 0x46` (the VK_F load)
2. within a small window (48 bytes), a `CALL [mem]` (the `GetKeyState` import thunk call)
3. followed by `TEST AX,AX` / `JNS rel32`

and computes the patched bytes from whatever `rel32` it finds, rather than assuming a fixed value. It also recognizes its own already-patched pattern (`TEST AX,AX ; JMP rel32 ; NOP`) so re-running it against a patched exe is a no-op instead of a double-patch.

If Sim Innovations changes *how* the key is read — different API, inlined differently, moved to another function — the pattern won't match. The script is written to fail closed: zero matches aborts with an error rather than guessing, and more than one match aborts as "too ambiguous" rather than picking one. There's no way around needing a fresh disassembler look in that case, since the binary is closed-source.

**Verification:** dry-run pattern matching against the shipped exe found exactly one match at `0xA59BD`; applying and re-running the scanner correctly reported "already patched, nothing to do" on the second pass.

---

## Security/Design Assessment

### What Sim Innovations did

- Implemented the camera-reset trigger twice: once through the documented, configurable bind system, and once as a raw, hardcoded `GetKeyState(VK_F)` poll with no corresponding setting, no way to disable it, and no relationship to the bind table.
- Chose a common single-letter key (F) that many users have bound to unrelated functions elsewhere (other add-ons, Windows shortcuts, EFB text entry) without any focus-scoping or collision awareness.
- Left the hardcoded poll active globally rather than scoping it to only when FSRealistic's own camera view is active and the sim window has focus.

### Why the fix works

Turning the unconditional `JNS`-guarded reset block into dead code (via the `JMP`) removes only the hardcoded poll's effect — the reset-zoom flag is never forced by this path again — while leaving the `GetKeyState` call (now with its result unused; harmless) and the entire configurable bind system, which most users still rely on for a legitimate reset-camera key, completely untouched.

### Residual Risk

- This patch is per-build: it works only while the instruction *pattern* around the VK_F check still matches. A future FSRealistic release that restructures this function (inlines the check differently, moves it to another key-code, etc.) will cause the scanner to find nothing, requiring a fresh look rather than blind re-application.
- Only the F-key hardcoded poll was investigated; no other hardcoded key polls elsewhere in the exe were audited, since they were out of scope for the reported symptom.

---

## References & Evidence

| Item | Contains |
|---|---|
| `patch_fsrealistic.py` | The byte patcher itself, with inline pattern-matching rationale |
| `FUN_1400a6590` (Ghidra, build analyzed) | Per-frame camera-update routine containing both the configurable bind check and the hardcoded VK_F poll |

---

**Analysis Method:** Manual Ghidra disassembly of the per-frame camera routine + Python byte-pattern verification
**Analysis Date:** 2026-07-13
**Analysis Tool Chain:** Ghidra (manual), Python `re`-based binary pattern scanner
