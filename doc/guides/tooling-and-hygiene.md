# Gradle / adb / tooling quirks

Companion to `CLAUDE.md`. Read this when a Gradle, adb, git, or instrumented-test-tooling command
misbehaves in a way whose error message doesn't name the real cause.

- `gradlew.bat test --tests <Class>` can fail with "Unknown command-line option '--tests'" on some
  project Gradle setups — if so, just run the full `gradlew.bat test` rather than fighting the flag.
- Git Bash mangles absolute Unix-style paths in `adb shell` commands (e.g. `/sdcard/foo` gets
  rewritten to a Windows path). Prefix with `MSYS_NO_PATHCONV=1` when passing device-side paths to
  `adb shell`.
- A double hyphen (`--`) is illegal *inside* an XML comment — an `AndroidManifest.xml` comment
  written with a prose "em-dash" (`foo -- bar`) fails the manifest merger with an opaque
  `ManifestMerger2$MergeFailureException: Error parsing AndroidManifest.xml`, not a message naming
  the `--`. Use a single hyphen, "to", or reword. (Kotlin/C++/Markdown `--` is fine; this is XML-only.)
- Instrumented tests need runtime-permission grants set up in the test, not just declared in the
  manifest: `@get:Rule val p = GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)` (from
  `androidx.test:rules`) — a `<uses-permission>` for a dangerous permission (RECORD_AUDIO) is not
  auto-granted to a headless instrumented run, and the capture silently returns silence/fails without it.
- LF→CRLF warnings on `git add`/`git commit` on Windows are harmless noise from line-ending
  normalization, not an error.
- Newer Android versions can break older Espresso versions: Android 16 (API 36) blocks the
  hidden-API reflection `InputManagerEventInjectionStrategy` relies on, so
  `espresso-core` below ~3.7.0 fails Compose-UI-driving instrumented tests (anything using
  `createComposeRule`/`createAndroidComposeRule` and `Espresso.onIdle`) with
  `NoSuchMethodException: android.hardware.input.InputManager.getInstance []`. If this resurfaces
  after an OS bump, bump `espresso-core` before assuming new tests themselves are broken.
