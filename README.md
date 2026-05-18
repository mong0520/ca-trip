# CA Road Trip 2026

Static itinerary site for our 2026 California road trip (SF · Big Sur · Monterey).

**Live:** https://mong0520.github.io/ca-trip/

## Update workflow

The site is rendered from a private Google Sheet via a local build pipeline (`build.py` + `Taskfile.yml`).

```bash
task deploy   # render → commit → push (GitHub Pages auto-rebuilds)
```

See [`CLAUDE.md`](CLAUDE.md) for full project context, build details, and source sheet info.
