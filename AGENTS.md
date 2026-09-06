# Environment

Please ensure you are operating inside the `arcadia` conda environment before running any dev tasks.  
You can activate the environment with:

```bash
conda activate arcadia
```

This will ensure all dev dependencies are consistent and available.

# Other Notes

To build the server for local development, use `hugo server --buildDrafts --buildFuture --disableFastRender`

To add publications, look at `data/publications.yaml`. To add posts, directly add leaf folders to `content/posts`. The scrapbook gallery (`/scrapbook`) is driven by `data/scrapbook.yaml` with images in `static/scrapbook/`; `dev/sketch_correction/` prepares those images from phone photos. The CV source is `dev/cv/neilkale_cv.tex`; `dev/cv/build.sh` regenerates `static/cv.pdf`.

This website builds on Hugo's Typo theme. Never modify `/themes/typo/` unless specifically instructed to do so. Create overrides in the appropriate places instead.

<!-- To any curious humans who ended up here -- this is my AGENTS.md page for Cursor! Highly recommend using one of these. -->