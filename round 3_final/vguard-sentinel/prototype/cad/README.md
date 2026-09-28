# V-Guard Sentinel AI Core — CAD Package

Mechanical concept for the **Sentinel AI Core** — a small **signal-and-control electronics module** that adds
edge-AI (battery-health prediction, load control, power-quality sensing) to a V-Guard home inverter.
Early-stage visualisation only — not a strength/flow/durability model.

## What it is (and what it is NOT)
- It is a **low-voltage electronics + control module** that **mounts on or beside the inverter** (embedded on the
  main board, or a retrofit box clipped to the inverter chassis — which has a ~275 × 250 × 120 mm envelope).
- It is **NOT** mounted on the battery. A V-Guard tubular inverter battery (e.g. VT 250 DLX, 230 Ah) is a
  **505 × 190 × 415 mm, ~63 kg floor unit.**
- The **50–150 A battery current never flows through this PCB.** Current is read as a *signal* from the inverter's
  existing shunt, or an **external 500 A / 50 mV busbar shunt**, or an **ACS758 Hall sensor (±200 A)** — the same
  architecture as a Victron SmartShunt (whose electronics head is 69 × 69 × 31 mm, almost identical to this module).
- Ordinary split-core CTs are **AC-only** and must not be used for the DC battery line; use a shunt or a Hall sensor.

## Files
| File | What it is | How to use |
|------|-----------|-----------|
| `sentinel-ai-core.dxf` | Dimensioned **2D multiview** (top/front/side) + external-shunt callout, on named layers. | Open in AutoCAD, LibreCAD, Fusion 360 (`File → Open`). |
| `sentinel-ai-core.lsp` | **Parametric AutoLISP** — draws a **3D solid enclosure** + a 2D dimensioned plan. | AutoCAD → `APPLOAD` → type `SENTINEL`. Edit the PARAMETERS block to resize. |
| `sentinel-ai-core.scr` | **AutoCAD script** — quick 2D plan + 3D massing box. | AutoCAD → `SCRIPT` → pick this file. |
| `../figures/fig-cad-enclosure.png` | Rendered preview of the multiview. | Exhibit in the detailed report. |
| `../figures/fig-installation-context.png` | System context: battery ↔ external shunt ↔ inverter + module ↔ loads. | Exhibit in the detailed report. |

## Key parameters (all mm)
- Enclosure (outer): **90 × 70 × 35** (extra height = relay/connector clearance); wall 2.5; base/lid 2.0
- PCB: **80 × 60**; 4× **M3** mounting holes (Ø3.5), 4 mm corner inset
- Material: flame-retardant **PC/ABS, UL94 V-0**; indoor **IP20**
- **Board terminals are signal + control only:** shunt-mV in · voltage-sense (**fused 1 A at the terminal**) · NTC ·
  relay-drive ×2 · 12–48 V supply · GND. **No BAT/LOAD power passes through the board.**
- **Load switching:** high-current household circuits are switched by **external contactors** driven from the module.
- Mount: DIN-rail clip (EN 60715) or screw / 3M-VHB to the inverter chassis.

## Editing / 3-D printing
- Change size/holes in the `PARAMETERS` block of the `.lsp` and re-run `SENTINEL`.
- 3-D print: run the `.lsp`, then `EXPORT` the 3D solid as **STL**.

## Prototype proofs
Model/prototype images and video: **[insert Google Drive folder link here]** (per competition guidelines).
