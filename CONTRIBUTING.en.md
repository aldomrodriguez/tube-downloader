# Contributing

[🇦🇷 Español](CONTRIBUTING.md) · 🇬🇧 **English**

Thanks for wanting to help! This guide explains how to report problems, suggest ideas
and send changes so they reach a published version quickly.

By taking part you agree to the [code of conduct](CODE_OF_CONDUCT.en.md).

Issues and pull requests can be written in English or Spanish.

## Reporting a bug

1. Make sure you're on the latest version: open the app with an internet connection and
   accept the update if it offers one. Many download errors come from YouTube changes
   that are already fixed in a newer release.
2. Search the [issues](https://github.com/aldomrodriguez/tube-downloader/issues) to see
   if someone already reported it. If so, add your case there instead of opening
   another.
3. Open a [bug report](https://github.com/aldomrodriguez/tube-downloader/issues/new?template=bug-report.yml)
   with the video link (if it's public), what you expected, what happened, the error
   message and your graphics card.

Security problems do **not** go in an issue: follow the
[security policy](SECURITY.en.md).

## Suggesting an idea

Open a [feature request](https://github.com/aldomrodriguez/tube-downloader/issues/new?template=feature-request.yml)
describing the problem it would solve. The app aims to stay simple — paste a link,
download, edit — so ideas that add options are weighed carefully. For big changes, it's
best to discuss them in an issue before writing code.

## Sending changes

### Setting up

You need Windows 10/11 and Python 3.11 or newer.

```powershell
git clone https://github.com/<your-username>/tube-downloader.git
cd tube-downloader
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

To try the final executable: `.\build.ps1` (it ends up at `dist\TubeDownloader.exe`).

### Workflow

1. Fork the repo and create a branch from `main` with a descriptive name
   (`fix/playlist-progress`, `feature/subtitles`).
2. Keep changes small and focused: one pull request per topic.
3. Test what you touched by hand. At a minimum:
   - a video that downloads in H.264 with no conversion (1080p or less),
   - a 4K one that needs conversion,
   - stopping a download halfway and closing the window during a conversion.
4. Open the pull request and fill in the template: what changes, why, and how you
   tested it. If it touches the interface, add a screenshot.

### Code style

- Follow the style of the file you're editing (PEP 8, 4 spaces, lines up to ~90
  characters).
- The interface is in Rioplatense Spanish ("pegá", "elegí"); comments and identifiers
  in the code are in English.
- Comments explain **why**, not what. If a decision isn't obvious (a hardware limit, a
  dependency bug), write it down.
- Never block the interface thread: heavy work goes in a separate thread and returns to
  the UI with `root.after(...)`.
- Don't add dependencies without discussing it first: each one makes the executable
  bigger.

### Commit messages

The project's own commits are written in Spanish, in the present tense; English is fine
for yours. Use a short title that says what changes and, if needed, a paragraph
explaining why:

```
Fix progress in playlists with private videos

yt-dlp skips private videos without notifying the hook, so the
counter stayed stuck on the previous one.
```

## Publishing versions (maintainers)

It's all in [RELEASING.en.md](RELEASING.en.md).

## License

By contributing, you agree that your work is published under the [GPL-3.0](LICENSE),
the same license as the project.
