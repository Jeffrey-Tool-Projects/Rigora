# Imeru cel-art generation record

Generated on 2026-11-11 with the built-in `image_gen` tool, using
`transparent_background=true` for every call. No CLI or API-key fallback was
used. Outputs are stored unchanged as four RGBA PNGs at 1024 × 1536.
The original plates were copied to `.audit/imeru-cel-before/` before replacement.

Each first input was the corresponding original plate. The second input for
the last three calls was the newly generated master. The arm plate deliberately
keeps its enlarged layout; the builder registers it to the body coordinates.

## Master

Output: `master.png`.

```text
Edit this exact Imeru full body illustration into an original theatrical Japanese cel animation character sheet style. Preserve EXACT canvas 1024x1536, pose, scale, positions of all anatomy, eye/mouth/wrist/shoulder coordinates and outfit silhouette for existing animation rig registration. Adult woman with midnight teal hair, ivory forelock, amber eyes, asymmetrical ivory/teal cropped jacket, charcoal inner top and shorts, opaque dark leggings and structured boots, brass celestial fittings and rust ribbon. Expressive tapered warm dark ink contours, deliberately angular flat cel shadows, base and one shadow per material, grouped hair locks, matte face, understated smile. Remove glossy gradients. True fully transparent alpha outside character, no background, haze, aura, floor shadow, text or panels. Entire body and boots visible. This must be a production master cutout, not a concept on a backdrop. Do not reposition character. No extra accessories.
```

## Underlay

Output: `underlay.png`.

```text
Image 1 is exact edit target: animation UNDERLAY with intentionally NO ARMS and NO EYES, EYEBROWS OR MOUTH. Image 2 is cel ink style reference ONLY. Restyle image 1 to perfectly match image 2's flat cel painting, dark tapered ink contours, flat grouped hair locks and angular shadows. Preserve image 1 exact 1024x1536 canvas, coordinates, proportions, pose, silhouette and ALL transparency. Keep blank face skin and armless torso intentional. Do NOT add arms or facial features from image 2. Base color plus one distinct cel shadow per material, no glossy gradients. Preserve outfit, hair, legs and boots. Output true transparent alpha production underlay, no haze, backdrop, shadow or glow. Everything at exactly image 1 positions for existing rig.
```

## Alternate expression and hands

Output: `alternates.png`.

```text
Image 1 exact edit target alternate animation plate. Image 2 cel ink style reference ONLY. Restyle image 1 to match image 2 dark tapered ink contours, clean grouped hair locks and flat angular cel shadows with base+one shadow per material. Preserve exact 1024x1536 canvas, ALL anatomical coordinates, same relaxed arms/pose, same clothing and proportions, CLOSED eyelids, small OPEN speaking mouth, OPEN palms and fingers pointing down. Do not use open eyes or relaxed hands from image 2. Preserve precise original eye mouth and wrist locations for rig. True transparent alpha outside character; no backdrop, haze, glow, floor shadow, labels. Complete head-to-boot character. No glossy gradient shading.
```

## Arms

Output: `arms.png`.

```text
Image 1 EXACT edit target: two isolated large animation arm sprites in their current positions. Image 2 ONLY style reference, do not copy its layout or small arm size. Restyle image 1 in image 2's original theatrical anime cel art, tapered warm dark ink outlines and flat angular cel shadows, base plus one shadow per material. Preserve EXACT 1024x1536 canvas, existing LARGE arm silhouettes, shoulder locations about (320,230)/(704,230), wrist (94,1030)/(930,1030), fingertips, sleeve folds, cuffs, jewelry and ribbon. Keep ONLY these two complete disconnected arms with hands, no head torso hair body legs. Maintain identical pixel positions for animation rig. True transparent alpha elsewhere, no haze glow backdrop or shadow. Preserve complete fingers inside canvas. Do not shrink arms or move them. No glossy gradients.
```

## Rebuild and inspect

```powershell
py -3 examples/puppet/imeru/build.py
Copy-Item examples/puppet/imeru.puppet rigora/resources/examples/puppet/imeru.puppet
py -3 -m pytest tests/test_example_imeru.py -q
py -3 scripts/verify_gui.py --source --output .audit/imeru-cel-gui
```

The package resource copy is required because the editor's example menu and
desktop-pet loader resolve that directory. Existing open documents retain their
loaded textures until reopened.

Verification on 2026-11-11 passed all 23 existing Imeru tests and the hidden
Windows OpenGL editor check, including save/reopen pixel equality. Neutral,
closed-eye, speaking and raised-hand renders were inspected. The updated PNG
and animated WebP previews come from this runtime. The Prove It Works principle
required these model renders in addition to inspecting the generated images.

The builder ignores alpha-one pixels when deciding mesh occupancy. Those faint
export residuals otherwise created disconnected cells and a stray ribbon
vertex. The stored source pixels and embedded texture bytes remain unchanged.
