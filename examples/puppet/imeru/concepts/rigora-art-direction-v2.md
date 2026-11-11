# Imeru for Rigora: ink-line cel-animation direction

This is the next illustration brief, prepared for the request on 2026-11-11.
It has not yet been rendered or accepted as final artwork.
Rigora is the application name. Imeru remains the character name.

The previous brief and `modern-full-body.png` document the existing design.
The prompts in `../artwork/README.md` document how the current animation plates
were made. They remain historical records, not instructions to silently replace
those plates. A new master needs a separately checked set of animation plates;
the existing meshes and UV coordinates do not automatically fit a new drawing.

## Art direction

Use the drawing economy of Japanese theatrical-animation character sheets,
with ink contours and deliberately shaped cel shadows. Keep the adult anatomy,
asymmetric tailoring and restrained celestial accents. The distinct visual
identity comes from tapered contours, angular fabric shadows, grouped hair
locks and an expressive but understated face. Avoid uniform finish everywhere.

The reference has extensive soft gradients and bright cloth highlights.
Replace that rendering language with two or three clearly separated values
per material. Face and hands receive the most drawing attention; large fabric
areas remain quiet. Do not add noise, distressed paper or random broken lines
to simulate drawing skill. Clean animation artwork still needs coherent forms.

## Ready-to-use prompt

```text
Create one full-body character illustration of Imeru for Rigora, a 2D character
animation application. Use the supplied modern-full-body.png as a character
identity and costume reference, not as a lighting or rendering reference.
Reinterpret the drawing style while keeping the recognizable design.

Visual direction: an original Japanese theatrical-animation character sheet
with expressive ink contours and economical cel painting. Aim for the visual
specificity of a character prepared for animation: a clear silhouette,
deliberately chosen shadow shapes and readable facial acting. No imitation of
a named artist or existing franchise is required.

Identity: an adult woman, approximately seven heads tall, with midnight-teal
hair, a single warm ivory forelock and amber eyes. Preserve the reference's
overall hair silhouette, hair part, asymmetric ivory-and-teal cropped jacket,
charcoal high-neck inner top, shorts with angular side panel, opaque dark
leggings, structured boots and small brass celestial fittings. Keep the rust
ribbon accent. Do not invent extra straps, buckles, jewelry or motifs.

Drawing: use dark warm ink with purposeful pressure variation. Give the outer
silhouette slightly firmer weight; taper facial and interior garment lines.
Use long, confident strokes and occasional natural joins. Group hair into
readable locks instead of outlining every strand. Draw the eyes as expressive
shapes with a stronger upper lid, simple iris values and one modest highlight.
Keep a small, specific, relaxed smile. Allow subtle natural differences between
the hands and brows without distorting anatomy or changing the neutral pose.

Color and light: use the existing ivory, charcoal, midnight teal, amber, brass
and rust palette. Use a base color and one principal shadow per material, with
an occasional small third value where form requires it. One broad upper-left
light governs every shadow. Keep skin matte. Hair highlights are a few flat,
designed shapes. Cloth folds start at seams, joints and tension points; large
panels stay calm. Brass has small discrete highlights, not luminous edging.
Let the face carry the clearest contrast and reduce detail toward the boots.

Composition: one frontal full-body figure in a relaxed A-pose, arms slightly
separated from the torso, shoulders level, both hands and all fingertips
readable, both boots completely inside the frame. Preserve adult proportions
and clothing coverage. No foreshortening, action pose or wind-blown additions.
Leave clear margin around the silhouette. Use a genuinely transparent alpha
background with clean edges and opaque character interiors.

Exclude airbrushed skin, wet-looking fabric, metallic skin, rendered 3D volume,
rim glow, bloom, lens effects, haze, gradient backdrop, ground shadow, patterned
iris sparkle, repetitive micro-folds and decorative detail without a structural
purpose. Do not substitute chibi proportions, a school uniform or a large bow.
No lettering, logo, signature, watermark, extra figures or presentation panels.
Keep the result readable as a small animated desktop character as well as at
full size. Deliver one coherent illustration, not a collage of drawing styles.
```

## Acceptance checks for the next render

- At thumbnail size, the ivory forelock, asymmetric sleeves and face remain readable.
- At full size, both hands have coherent anatomy; garment seams, clasps and ornaments connect to real structures.
- Shadow direction stays consistent across face, hair, sleeves and boots. Cloth does not look like polished plastic.
- The face has specific expression and line decisions rather than uniformly smooth, mirrored features.
- Transparent areas contain no baked checkerboard, dark halo, haze or floor shadow. Check the actual alpha channel.
- No new costume elements or proportional drift require an unplanned character redesign.

Review the rendered image against these checks before calling the direction
successful. A prompt alone cannot establish the appearance of a future image.

## Focused revision prompt

If the first render still looks airbrushed, use only this correction with that
render as the edit target. Do not change all the drawing choices at once.

```text
Change only the shading treatment of this image. Preserve the exact character,
face, anatomy, costume, outline, pose, framing and transparent background.
Replace broad smooth gradients and glossy fabric highlights with a base color
and one clean cel-shadow shape per material under the existing upper-left
light. Keep the ink contours intact. Retain small brass highlights. Do not add
paper texture, grain, distress, new folds, ornaments or lighting effects.
```
