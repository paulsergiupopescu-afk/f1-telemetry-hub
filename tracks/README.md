# Imported circuit data

These racing-line files were imported from the user-supplied
`f1-25-telemetry-application-main` project.

Each CSV-style text file contains:

`distance, pos_z, pos_x, pos_y, drs, sector`

The application reads the files through `f1_track_data.py`. Raw files are kept
unchanged so their coordinate and sector data remain reusable. The loader
normalizes filenames, removes duplicate distance samples, simplifies lines for
display, and supports both source runs and PyInstaller bundles.

The supplied data covers 27 mapped circuits. A dashboard continues to operate
normally when no imported line is available for the current track.
