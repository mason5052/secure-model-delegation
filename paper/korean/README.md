# Korean Manuscript Collaboration

This is the editable Korean publication draft by Junkuk Kim and Jinyoung Choi.
It uses a single 5.5-inch text column and author-year citations. The layout does
not indicate submission to, review by, or acceptance at a particular venue.

## Files

| File | Purpose |
| --- | --- |
| [secure-model-delegation-ko.tex](secure-model-delegation-ko.tex) | Canonical editable manuscript. |
| [architecture-ko.pdf](architecture-ko.pdf) | Vector implementation diagram. |
| [protocol-ko.pdf](protocol-ko.pdf) | Vector paired-evaluation design. |
| [baseline-ko.pdf](baseline-ko.pdf) | Vector comparison of the two route metrics. |
| [build-figures-ko.py](build-figures-ko.py) | Editable source for all three figures. |
| [secure-model-delegation-ko-source.zip](secure-model-delegation-ko-source.zip) | Downloadable copy of the manuscript, figures, generator, and instructions. |

Edit the LaTeX and figure generator directly. The ZIP is a convenience snapshot,
not a separate manuscript version. Regenerate it whenever the source changes.
The main manuscript PDF is built locally; the figure PDFs are tracked assets.

Historical evaluation results refer to source revision `4706804`, as cited in
the manuscript. Later implementation edits on the repository default branch
do not update those results automatically.

## Build the manuscript

From this directory, use Tectonic:

```bash
tectonic -X compile secure-model-delegation-ko.tex
```

Or use XeLaTeX twice to resolve citations and cross-references:

```bash
xelatex secure-model-delegation-ko.tex
xelatex secure-model-delegation-ko.tex
```

Required standard packages include `geometry`, `fontspec`, `xeCJK`, `amsmath`,
`amssymb`, `graphicx`, `booktabs`, `array`, `natbib`, `caption`, and `hyperref`.
Tectonic may download public TeX packages; it builds the manuscript locally.

The source supports Times New Roman or TeX Gyre Termes for Latin text;
AppleMyungjo, Noto Serif CJK KR, or NanumMyeongjo for Korean text; and AppleGothic
or Noto Sans CJK KR for Korean sans-serif text. On Linux, install Noto CJK fonts
with a TeX Live installation that includes the listed packages and Latin Modern
Mono. On macOS, the supplied Apple font choices are used when available. Fonts
are not redistributed in this repository. Change the font selections if your
platform uses different installed fonts.

## Edit the figures

The existing PDF assets are sufficient to build the paper. Regeneration needs
Python, ReportLab, and a Korean TrueType font:

```bash
python -m pip install reportlab
python build-figures-ko.py --figure all
```

Use `--figure architecture`, `--figure protocol`, or `--figure baseline` to
regenerate one asset. The generator accepts an installed font with `--font`.
AppleGothic is supported on macOS. NanumGothic TrueType, provided by the
`fonts-nanum` package on common Linux distributions, is another supported choice.
All figures are vector PDFs, 396 PDF points wide, with labels at least 8.5 points.
Rebuild and visually check the manuscript after editing them.

## Refresh the source bundle

From this directory, include only these public files:

```bash
python -m zipfile -c secure-model-delegation-ko-source.zip \
  secure-model-delegation-ko.tex architecture-ko.pdf protocol-ko.pdf \
  baseline-ko.pdf build-figures-ko.py README.md .gitignore
```

Do not add the locally compiled manuscript PDF or private preparation material
to the source archive.

## Collaborate

1. Create a branch for the proposed change. Contributors without repository
   write access can fork this public repository and open a pull request.
2. Edit the canonical LaTeX or figure generator and rebuild the manuscript.
3. Check equations, table values, denominators, captions, and Korean text. Keep
   completed observations separate from planned work and pending human review.
4. Update the source ZIP from the current allowlisted files and open a pull
   request describing the change and validation.

Do not treat the prototype's route names as completed model tasks or the local
mock-body records as network receipt. The manuscript explains the authored
ordinal route metric and the limits of the fixed code transformation.

Only anonymized discussion of practitioner-prompt research belongs in this
workspace. Original prompts, full conversation exports, private mappings,
blinded reviewer packets, response files, and private analysis reports are not
part of the public collaboration package. Do not add them to a branch or ZIP.
