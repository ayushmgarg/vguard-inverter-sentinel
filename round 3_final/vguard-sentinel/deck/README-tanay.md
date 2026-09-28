# Tanay simulation-aligned deck additions

These are additive deliverables. The original deck, PDF, source, and assets are
left untouched:

- `storyboard-tanay.html` — div-based source of truth for the revised 16-slide deck.
- `build_from_html-tanay.py` — converts that storyboard to PowerPoint.
- `VGuard-Sentinel-Finale-Deck-tanay.pptx` — generated 16:9 presentation.
- `animated_prototype-tanay.html` — two-minute browser-playable simulation walkthrough.
- `VGuard-Sentinel-Prototype-Analysis-tanay.mp4` — rendered 120-second analytical
  animation showing the simulated signal path, outage controller, synthetic health
  band, AC-stream analysis, and simulated cluster-of-homes central learning.
- `make_video-tanay.py` — deterministic renderer for the MP4 (15 fps, 1280×720).

The revised material reconciles the report with the repository and labels the
evidence correctly: synthetic data and host-side replay are implemented; real
batteries, homes, ESP32 silicon, and practical experiments are not. The
cluster-of-homes scene is a simulated central-learning illustration. Federated
learning remains designed but deferred.

Regenerate the PPT from the HTML source with:

```bash
python3 build_from_html-tanay.py
```

Open `animated_prototype-tanay.html` in a browser for the 120-second walkthrough.
The MP4 is silent by design and carries a persistent computer-simulation disclaimer;
it does not depict practical experiments or deployed houses.
