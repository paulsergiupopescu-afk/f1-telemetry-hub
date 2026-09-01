# Runtime assets

This directory is bundled into the executable.

- `brendon_leigh_setups_v1_5.json` is the normalized setup library used by the
  Pre-Race screen.
- `race_command_icon_v2.ico` is the Windows executable/window icon.
- `race_command_icon_v2.png` is the Tk fallback icon.
- `source/race_command_icon_v2_source.png` is the editable high-resolution source.

Original setup PDFs stay in `setup_packages/1.5` and are not bundled.
Only the normalized JSON and two `v2` runtime icons are included in production
builds. Older icon files are organized under `source/` solely for historical
comparison and future design work.
