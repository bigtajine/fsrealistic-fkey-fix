# FSRealistic F-key fix

Small binary patch that stops FSRealistic from resetting the camera every time you press **F**.

## The problem

If you use FSRealistic with MSFS, pressing F snaps/re-zooms the camera. It does this even if:

- you've deleted the "Reset camera" bind from every controller in FSRealistic's settings, and
- the sim window isn't even focused (typing F in the EFB, alt-tabbed, whatever).

There's no way to turn it off. `config.json` has a `reset_camera_button_id`, but that only lets you add a *second* key — the F key is baked into the exe. People have been complaining about this on the MSFS forums since 2022 and it's never been fixed.

## What's actually going on

FSRealistic's per-frame camera code checks the F key directly:

```
MOV  ECX, 0x46            ; 0x46 = VK_F
CALL [GetKeyState]
TEST AX, AX
JNS  skip                 ; if F isn't down, skip
...                       ; otherwise: force reset-zoom flag + default zoom
```

So any time F is held down it resets the zoom, no matter what your binds say. `GetKeyState` reads the global keyboard, which is why focus doesn't matter.

The normal, configurable reset-camera bind is handled by different code and this doesn't touch it — it keeps working like before.

## The fix

One instruction. Change that conditional `JNS` (skip only when F is up) into an unconditional jump so the reset block never runs.

At file offset `0xA59BD`:

```
0F 89 E4 00 00 00   ->   E9 E5 00 00 00 90
```

That's it. The `GetKeyState` call is left alone since it's harmless; only the branch changes.

## Usage

Close FSRealistic first (the exe is locked while it's running), then:

```
python patch_fsrealistic.py "C:\path\to\FSRealistic\FSRealistic.exe"
```

It checks the original bytes before writing, so it won't touch a different version by mistake, and it saves a `FSRealistic.exe.bak` the first time. To undo, just copy the `.bak` back over the exe.

## Notes

The patcher and this README are all that's here — you point it at your own installed copy. Nothing from FSRealistic is redistributed.
