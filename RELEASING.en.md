# How to publish a version

[🇦🇷 Español](RELEASING.md) · 🇬🇧 **English**

A guide for maintainers. Every version published in
[Releases](https://github.com/aldomrodriguez/tube-downloader/releases) reaches all
users through auto-update, so this process is all it takes to ship a change.

## Steps

1. **Make your changes** and test them (see the checklist in
   [CONTRIBUTING.en.md](CONTRIBUTING.en.md#workflow)).

2. **Bump the version** in `app.py`:

   ```python
   APP_VERSION = "1.0.1"
   ```

   It's the only place the version lives: `build.ps1` copies it into the `.exe`
   metadata and the updater compares it against the release tag.

3. **Record the changes** in [`CHANGELOG.md`](CHANGELOG.md) (Spanish) and
   [`CHANGELOG.en.md`](CHANGELOG.en.md) (English), at the top, with the date and the
   link at the bottom of the file:

   ```markdown
   ## [1.0.1] — 2026-12-05

   - Fixes downloading Shorts.

   [1.0.1]: https://github.com/aldomrodriguez/tube-downloader/releases/tag/v1.0.1
   ```

4. **Build:**

   ```powershell
   .\build.ps1
   ```

   It installs the newest yt-dlp, packages and signs `dist\TubeDownloader.exe`. Open it
   and try a download before moving on.

5. **Commit and push:**

   ```powershell
   git add -A
   git commit -m "Version 1.0.1"
   git push
   ```

6. **Publish the release** with [GitHub CLI](https://cli.github.com/):

   Write the notes in a file (for example `notes.md`, saved as UTF-8) and pass it with
   `--notes-file`. Typing them straight into the command with `--notes` can corrupt
   accented characters depending on the console, and that's how they'd show up in the
   app's update prompt.

   ```powershell
   gh release create v1.0.1 dist\TubeDownloader.exe `
     --title "Tube Downloader 1.0.1" `
     --notes-file notes.md
   ```

   Or from the web: **Releases → Draft a new release**, tag `v1.0.1`, and attach
   `dist\TubeDownloader.exe`.

   The app shows these notes to users, who read Spanish, so write them in Spanish.

## Rules you can't break

The updater depends on these three things; if any fails, users don't see the update:

- The tag is `v` + the `APP_VERSION` value (for example `v1.0.1`).
- The attached executable is named exactly `TubeDownloader.exe`.
- The release is not marked as a draft or a pre-release. Conversely, marking it that
  way is how you upload something for testing without it reaching users.

The release notes appear in the update prompt (the first ~280 characters), so keep
them short and about what matters to the user.

## Which number to use

Semantic versioning, `MAJOR.MINOR.PATCH`:

| Change | Example | New version |
|---|---|---|
| Fixes, updated yt-dlp | Shorts work again | `1.0.0` → `1.0.1` |
| New features | Download audio only | `1.0.1` → `1.1.0` |
| Big or incompatible changes | Full redesign | `1.1.0` → `2.0.0` |

## Maintenance: rebuild even with no changes

yt-dlp ships inside the executable. When YouTube changes something, downloads can start
failing, and the only way to fix it for users is to publish a new version built with
the updated yt-dlp.

So it's worth publishing a patch release:

- as soon as someone reports download errors that didn't happen before, and
- every so often (say, once a month) even if nobody has reported anything.

In that case steps 2 to 6 are enough, with a note like
"- yt-dlp actualizado para seguir los cambios de YouTube."

## If something goes wrong

- **You published a broken exe:** publish a newer version with the fix right away.
  Deleting the release isn't enough, because anyone who already updated stays on the
  broken exe until there's a newer one.
- **Users don't see the update:** check the three rules above. You can see what the app
  sees with:

  ```powershell
  .\venv\Scripts\python.exe -c "import updater; print(updater.check_latest('0.0.0'))"
  ```
