# Korean Manuscript Collaboration

The latest Korean working draft by Junkuk Kim and Jinyoung Choi is available
as a [16-page PDF](secure-model-delegation-ko.pdf). It uses a two-column,
10pt letter layout, full-width title and summary, eight wide tables and four
vector figures. It is a review draft, not a venue submission or acceptance.

## Read and edit

| File | Purpose |
| --- | --- |
| [secure-model-delegation-ko.pdf](secure-model-delegation-ko.pdf) | Latest compiled review PDF. |
| [secure-model-delegation-ko.tex](secure-model-delegation-ko.tex) | Canonical editable manuscript. |
| [secure-model-delegation-ko-source.zip](secure-model-delegation-ko-source.zip) | The same LaTeX, four figures, generator and build notes. |
| [architecture-ko.pdf](architecture-ko.pdf) | Historical implementation and observation boundaries. |
| [protocol-ko.pdf](protocol-ko.pdf) | Paired metadata-ablation design. |
| [baseline-ko.pdf](baseline-ko.pdf) | Historical authored route metrics. |
| [live-model-ko.pdf](live-model-ko.pdf) | Actual model comparison through the shared backend. |
| [build-figures-ko.py](build-figures-ko.py) | Editable source for all four vector figures. |
| [BUILD.txt](BUILD.txt) | Build conditions, results boundaries and preservation notes. |
| [paper-style-analysis.txt](paper-style-analysis.txt) | Referenced scholarly layout analysis. |

Start with pages 5-8 for model settings and experiment methods, pages 11-12
for the 108-run comparison, and pages 13-14 for the real-provider diagnostic
and remaining limitations. The exact scalar criteria were fixed by the
research process; independent human policy and semantic review is pending.

The historical 1,400/210/36-case results are rule-based simulation results.
The later study has 12 authored task groups, three recipient profiles and
108 A/B/C executions, not 108 independent tasks. A/B/C field checks pass in
36/36, 32/36 and 34/36 conditions. B has protected fixture values in two of
twelve loopback bodies; C makes no HTTP calls, so its received-body protection
is unmeasured. The separate real API diagnostic has eleven calls including a
probe: six of ten task replies pass, versus seven of ten original Qwen B
answers to the same transformed messages. It is not a repeated full routing
comparison or evidence of aggregate external-model benefit.

The corresponding execution code is in
[PR #2](https://github.com/mason5052/secure-model-delegation/pull/2), commit
`9a9f97a21f29fc0ab41748766618b73bfb8046b3`. This paper-only branch starts from
main and does not include or merge the application changes in that PR.

## Build

From this directory, use Tectonic:

```bash
tectonic -X compile secure-model-delegation-ko.tex
```

Or run XeLaTeX twice:

```bash
xelatex secure-model-delegation-ko.tex
xelatex secure-model-delegation-ko.tex
```

The verified build used Tectonic 0.17.0. Standard packages include `geometry`,
`fontspec`, `xeCJK`, `amsmath`, `amssymb`, `graphicx`, `booktabs`, `array`,
`natbib`, `caption`, `hyperref` and `dblfloatfix`. Tectonic may download public
packages; it builds the manuscript locally.

The source declares Latin and Korean font fallbacks. The verified Mac build
used Times New Roman, AppleMyungjo, AppleGothic and Menlo. On another system,
install the declared Noto CJK or Nanum font families or adjust the font choices.
Fonts are not redistributed.

The existing vector PDFs are sufficient to build the manuscript. Optional
figure editing requires Python, ReportLab and an installed Korean TrueType font:

```bash
python -m pip install reportlab
python build-figures-ko.py --figure all
python build-figures-ko.py --figure live-model
```

The generator accepts `--font`. Rebuild and visually inspect the manuscript
after editing a figure. Keep the historical three figure files unchanged
unless a separately explained revision is intended.

## Refresh the source snapshot

The ZIP contains exactly these eight public files. It is a convenience snapshot
of the same canonical files, not a separate manuscript version:

```bash
python -m zipfile -c secure-model-delegation-ko-source.zip \
  secure-model-delegation-ko.tex architecture-ko.pdf protocol-ko.pdf \
  baseline-ko.pdf live-model-ko.pdf build-figures-ko.py BUILD.txt \
  paper-style-analysis.txt
```

Keep the compiled PDF outside the source ZIP. After any source change, rebuild
the tracked PDF and ZIP, unpack the ZIP into a clean directory, and confirm
that the extracted source builds the same page text and layout.

## Review boundaries

Independent reviewer packets, responses, expected-answer fixtures, original
work prompts, private source mappings, full model/HTTP logs and account or
credential material are outside this public package. The paper publishes
aggregate observations with their limits, not those private artifacts.

The private pre-revision snapshots are retained in the owner's research
workspace; earlier public manuscript versions remain in Git history. No English
manuscript or preserved research code, policies, labels or datasets are changed
by this paper revision. CI preserves those paths and all paper paths except
nine explicitly reviewed Korean manuscript assets.
