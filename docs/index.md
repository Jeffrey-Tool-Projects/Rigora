---
title: Overview
description: Build a 2D character, animate it, and use it in a live performance or on your desktop.
permalink: /
home: true
---

<section class="hero">
  <div>
    <p class="eyebrow">The Rigora handbook</p>
    <h1>Bring your<br>characters to life.</h1>
    <p class="lead">Edit a 2D rig, build an animation, or perform live. Rigora keeps the character and its motion together in a portable <code>.puppet</code> file.</p>
    <div class="actions"><a class="button" href="{{ '/getting-started/' | relative_url }}">Start with Imeru</a><a class="button secondary" href="{{ '/getting-started-zh-tw/' | relative_url }}">繁體中文入門</a></div>
  </div>
  <div class="hero-art"><img src="{{ '/assets/imeru.png' | relative_url }}" alt="Imeru, the bundled character with teal hair and an ivory and teal jacket" width="512" height="832"></div>
</section>

## One character, several ways to use it

Start with the bundled Imeru rig or import your artwork. Use parameters,
deformers, and bones to control the character. Play and record motion, connect
live inputs, or load the model as a desktop companion.

<div class="cards">
  <a class="card" href="{{ '/getting-started/' | relative_url }}"><span class="card-number">01 / SET UP</span><h2>Open your first character</h2><p>Install Rigora in a virtual environment and play a bundled motion.</p></a>
  <a class="card" href="{{ '/user-guide/' | relative_url }}"><span class="card-number">02 / CREATE</span><h2>Edit, animate, and perform</h2><p>Find the workflow for your artwork, recording, or desktop companion.</p></a>
  <a class="card" href="{{ '/reference/' | relative_url }}"><span class="card-number">03 / CONNECT</span><h2>Use commands and formats</h2><p>Inspect archives, validate a rig, or connect an MCP client.</p></a>
  <a class="card" href="{{ '/development/' | relative_url }}"><span class="card-number">04 / BUILD</span><h2>Work on Rigora</h2><p>Understand the source layout and run the project checks.</p></a>
</div>

## Choose the installation you need

The editor uses Qt and OpenGL. The core package also supports archive and schema
operations without opening a window. Optional packages add webcam tracking,
microphone input, virtual camera, NDI, and global hotkeys.

Rigora is available as source under the
[MIT license](https://github.com/Jeffrey-Tool-Projects/Rigora/blob/main/LICENSE).
The installation guide uses a repository checkout. It does not assume a
published PyPI package.
