# FSRealistic F‑Key Fix

A small patch that disables FSRealistic’s hardcoded camera reset when the **F** key is pressed.

## Overview
FSRealistic directly checks `VK_F` via `GetKeyState` and triggers a camera reset whenever the key is down. This happens regardless of user‑configured binds or application focus.

## Patch Details
The fix replaces the conditional jump that guards the F‑key reset block:

```
0F 89 E4 00 00 00   →   E9 E5 00 00 00 90
```

The script locates this block by scanning for the instruction pattern (MOV → CALL GetKeyState → TEST → JNS). It patches only when exactly one match is found.

## Usage
Close FSRealistic, then run:

```
python patch_fsrealistic.py "C:\path\to\FSRealistic\FSRealistic.exe"
```

A `.bak` file is created on first run. Restoring it reverts the change.  
After FSRealistic updates, rerun the script; it will either apply the patch again or report that the pattern no longer matches.

## Notes
This repository contains only the patcher and documentation. No FSRealistic files are included.
