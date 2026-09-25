# PuddleLoom ScoreLight - free PDF-to-MusicXML converter

This **public** GitHub Actions workflow uses Audiveris 5.11.0 on a
standard GitHub-hosted Ubuntu runner. It is a PDF **converter only**:
PuddleLoom Studio does playback, animations, instruments and MP4 export.

## On Android: convert a PDF for free

1. Open the scorelight/input folder in this repository.
2. Tap **Add file → Upload files**, choose your PDF and commit it to main.
   (15 MB maximum per PDF, four PDFs per commit.)
3. Open the **Actions** tab and select **ScoreLight - PDF to MusicXML**.
   Open the new conversion run that appeared after the upload.
4. Once the run is green, download **scorelight-musicxml-NNN.zip** from
   its **Artifacts** section. It contains the plain MusicXML file and
   a short JSON conversion report.
5. Unzip it on your phone using Android Files. Open
   https://puddle.loomstudio.workers.dev/scorelight and import the
   MusicXML file. Review the notes against the original PDF, then
   choose instruments, play or export the animated score.

### Enhanced piano recognition (automatically attempted)

The converter now first produces the ordinary Audiveris MusicXML and then
attempts a second pass that recognizes each **complete two-staff piano system**
separately, retaining the upper/lower staff relationship while stitching the
measures into one piano part. When the enhanced candidate passes structural
checks and has at least as many detected notes and measures as the baseline,
the ZIP includes a clearly labeled `*-ENHANCED-REVIEW.musicxml` alongside the
original baseline MusicXML. The `conversion-report.json` identifies the
preferred file, recognized pages and systems, coverage counts and warnings.

**An increased note count is not proof of correct notes.** Incorrect pitches,
durations, ties, beats and missing systems can remain. The enhanced MusicXML
is explicitly marked for human comparison with the original score.
The converter keeps the baseline when system-wise OCR fails and never
pretends to repair an unrecognized score. For non-piano scores, the normal
Audiveris output remains available. A manual run offers a baseline-only
switch.

### Automatic two-hour PDF cleanup

The [cleanup workflow](../../actions/workflows/scorelight-pdf-cleanup.yml)
runs every **two hours** and removes PDFs once they have been uploaded for
at least **two hours**. Depending on the scheduled scan and GitHub delays,
removal generally happens two to four hours after upload. The workflow
runs unit tests and shares a concurrency lock with the converter so it
doesn't remove inputs during conversion.

It never deletes the input README, converter source or MusicXML downloads.
Converted MusicXML artifacts still expire after **one day**.

You can run the cleaner manually from Actions. Its manual default is
a **dry run**, showing what it would delete. Disable dry_run to remove
eligible PDFs immediately.

**This is repository housekeeping, not secure erasure.** Uploaded PDFs
remain in public Git history even after automated deletion from main.
Only upload files you have permission to publish. If conversion fails,
retrieve or re-upload the PDF before its two-hour retention period expires.

### Re-convert a PDF already uploaded here

Open Actions → ScoreLight - PDF to MusicXML → Run workflow. Enter its
existing path in the pdf_path field, such as
scorelight/input/my-score.pdf. Select Run workflow.

### Test the installation without a PDF

Open Actions → ScoreLight - PDF to MusicXML → Run workflow.
Choose test_install = true. This tests the real Audiveris launcher
without consuming your upload.

## Free and public: important constraints

- A standard Ubuntu runner on a public repo is free under GitHub's
  public Actions terms. This does not use paid hosted runners.
- The converted MusicXML artifact expires **one day after conversion**.
  Download it promptly; then ScoreLight can reuse it anytime.
- The source PDF **will be public** if you upload it through GitHub's
  repository file uploader. Deleting the file does not remove it from
  existing Git commits. Never upload private documents or PDFs you
  lack permission to redistribute.
- Recognition errors are possible. Confirm notes, triplets, time
  signature, repeats and timing before using the output.
- Only input PDFs directly in scorelight/input/ are accepted.
- The workflow never commits output files or uses repository secrets.
  Its permissions are contents: read, and only MusicXML artifacts
  are uploaded (the PDF is never copied into the artifact).
- Audiveris is open-source software; the workflow installs its
  official release using dpkg-deb extraction, avoiding the failed
  apt-get installation seen on free Colab sessions.

Audiveris license: AGPL-3.0.
