build a parametric mosfet search web app.

# Table Columns

The table has these columns, all of them sortable:

* Manufacturer and part number (MPN)
* Substrate - GaN, Si, SiC
* Housing
* Vds break down (Vds_max)
* RdsON_max
* Id - max drain current
* Idp - max pulse drain current
* Qsw - switching charge
* Qg - total gate charge
* Qrr - reverse recovery charge
* Vsd - body diode forward voltage, make values absolute
* V_pl - Miller plateau voltage
* V_gs(th) - Gate drive threshold voltage
* Qgd/Qgs - gate charge ratios
* date

# Table Filter

It has a sidebar with a filter form:

* range sliders for:
    * Vds_max (Vds_max)
    * RdsON_max
    * Id
    * Qsw
    * Qg
    * Qrr
    * Vsd
    * Qgd/Qgs
* tick-boxes for:
    * manufacturer
    * housing

# Table Details

* The range slider have a 200ms update debounce for smooth UX.
* During the slider debounce delay, the table fades out to 50% opacity.
* Store the slider values in a localStorage so they persist page reloads.
* All sliders are logarithmic
* Format numbers with d3.format, stripping any leading zeros and unnecessary decimal points.
* The MPN has link to the datasheet. The PDF file is served through the API, get file path with
  `get_datasheets_path(mfr,mpn)`. HTTP Content-Disposition=inline.
* Display housing values that match a regex according to this table:

| Regex                                            | Displayed Housing |
|--------------------------------------------------|-------------------|
| I?TO-?220.*                                      | TO-220            |
| TO-?247[ -]4\s*[a-zA-Z].+                        | TO-247-4          |
| I?TO-?247.* (and not matching previous TO-247-4) | TO-247            |

# Data source

Use the database object parts_db in dslib/store.py to retrieve parts.

# Libraries

* For the backend use FastAPI.
* For the front-end use SvelteKit.
* Use `svelte-range-slider-pips` for the range sliders

Work in /Users/fab/dev/pv/pwr-mosfet-lib/web

# MOSFET details

# Done

* add a free text search field above the sliders to search for Mfr, MPN, housing, tech and string representations of all
  numeric values. the search term supports *-wildcards
* there is a special search command 'similar(<mpn>)', which will find similar parts to the one selected by <mpn>.
* add a small button next to MPN to find similar parts. similarity is computed with log-normalized weighted Euclidean
  distance over the numeric specs only.

* encode the state of the page in the url hash fragment so the user can bookmark the search. consider similarity search
  and all filter values. round numeric values to 5 significant places.
* next to the similarity button add a round button to mark the part with a color. the button changes the color when
  clicked, cycling through a color cycle similar to the color markers in MacOS finder. store the state in localStorage.


* make the page responsive for mobile devices
* add a dark-mode button

# candidate prompts

* the first button puts `similar(<mpn>)` in the search box, triggering a similar parts search. chose an adequate icon
  for that button

# visual design

https://www.reddit.com/r/ClaudeCode/comments/1q8g96d/using_claude_code_to_build_a_website_what_skills/

* /plugin frontend-design
* old-school tech
  """
  Typography: IBM Plex Serif for body and brand, IBM Plex Mono for every numeric value, MPN, unit, count, and section
  label. Small-caps section headings use the mono face at 10 px with 0.18 em letter-spacing — the typography you see at
  the top of every column on a Motorola or IRF datasheet.
    - Light mode palette: cream paper #F1EBDE, ink #1A1714, blueprint blue #2A3C64 (links, slider accent), oxblood red
      #82221B (errors). The table column headers run inverted — ink-on-cream — like the printed-tab section dividers in
      a real
      datasheet, with sorted columns swapping in the blueprint accent.
    - Dark mode: warm amber phosphor #FFB347 / #D99544 on near-black #15130D, with a subtle text-shadow glow on the
      whole
      body to simulate phosphor bleed. Column headers invert to amber-on-black.
    - Header bar: a fixed datasheet-style title block — N-channel MOSFET schematic symbol (custom SVG), "FETLIB"
      wordmark,
      italic tagline, double-rule underline. Filtered-count readout on the right in mono.
    - Section dividers: triple-rule (3 px double border) under the sidebar header, under the page header. Single-thin
      rule
      under each filter section.
    - Sidebar: paper-tone background, mono-uppercase section labels, square checkbox lists (no rounded corners
      anywhere —
      datasheets never had border-radius). Buttons invert on hover: black fill with cream text, like a stamp.
    - Range sliders: 4 px ink-colored tracks, square handles, square float bubbles (border-radius: 0 everywhere). Mono
      labels.
    - Loading state: a blinking ▌ cursor + "loading parts library…" in mono — terminal energy.
    - Error / similarity banners: small mono SIM / ERR pills with hard borders, sentence-style serif body.
    - Color tags + ≈ buttons: retained in the rows; their hover treatments now match the banner button style (invert on
      hover, no border radius).

"""

* add a edit columns button, which opens a small menu with checkboxes to select the visible columns

* add another button next to Mpn that opens a overlay, displaying all parts data in tabular form

Write a program that loads all parts from database (parts_db in dslib/store.py) and for those with missing fields
runs compile_part_datasheet(). It then generates a `Part` object similar to how `compute_part_powerloss` does it (
without the powerloss computation). It then writes the part with the fresh specs back to parts_db.

# parser

I want you to write a program to extract tabular data from MOSFET datasheets.
To describe a part's characteristics, manufacturers follow a common structure in pdf documents:

* Parameter Name and/or Symbol (e.g. I_D, V_gs)
* Test Conditions
* Characteristic Values, most of the time with Min., Typ., Max. columns

Implementation details:

* work directly with the pdf (dont use tabular or Camelot). create a "spatial query" algorithm the groups the individual
  characters into words. detect table headings (see `head_re` in my code), columns and symbols/parameters. I've already
  implemented something similar in dslib/pdf/sheet/__init__.py ,
* to normalize the parameter names you can use `get_field_detect_regex()`
* to capture a parameter field use the datastructure `dslib.field.Field`. If a characteristic has no min/typ/max values,
  assume it is typ.
* To verify the data correctness, I have prepared some reference samples. you find the samples in `test_pdf_parse`. test
  your code with the real pdfs.
* Skip scanned datasheets that need OCR

Write your code in dslib/v2 .

How would you implement the data extraction?
How would you approach that?

# not necessary:

* The temperature test condition often appears below the section heading

# Gate Charge curve

Most mosfet datasheets don't specify the Miller-Plateu Voltage Vpl in the tabular data.
It can be determined by finding the miller plateau of the Gate Charge curve.
The gate charge curve usually starts at 0 and increases linearely, until it reaches the miller plateu (y=Vpl).
After the mostly flat part (sometimes with slight inclination) it starts to linearely increase again.

Write a program that finds the Gate Charge Curve chart in a PDF and determines Vpl.
Notice the different styling of the charts across manufactureres. The curves look all quite similar.
Use sample files from test/tests.py. Some reference data includes Vpl, which you can use to validate your program.
Put your code in viz/.

Find charts by their caption with this regular expression (case insensitive):
r"(([0-9]*\s*typ(\.|ycal)\s+)?gate[\s-]+charge\s+(curve|vs|waveforms?).*|(Fig.?(ure)?)\s*[0-9]+\s*[.:]\s*Gate[\s-]
+Charge.*)"

In case you find captions in the PDF texts that you might think should match  (curve, diagram, ...) in the pdf text tha

* are there any captions you have seen in the text that you might think should match? e.g. using synomys for "curve" or
  "diagram"? then optimize the regex to match these synonym

Now use the refresh script to find missing Vpl using the chart-extractor.
If a value

* Vpl valid range is (-1, 10)
*

use this to get an

* the chart in BSB056N10NN3GXUMA2.pdf is rastered with a caption "14 Typ. gate charge". at caption based chart detection
  with regex for matching similar captions
* in BSZ084N08NS5ATMA1.pdf there are actually 3 curves hardly distinguishable from each other. The curves have small
  labels next to them. Ignore the labels as they might interfere with finding the plateau.

the regular expression (python):
r'(?P<conds_mTm>=name)?^([^\n]*\n){0,2}[-    _.,;:#*"\'()\[\]a-z0-9]{,30}(capacitance|C[ _]?[a-z]{1,3})
*[-    _.,;:#*"\'()\[\]a-z0-9]* *\n((?P<conds_ml>(?P<cond_sym>([a-z]{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]
{1,6}\))?)) *[=≈] *(((?P<cond_val>(-?[0-9]+(\.[0-9]+)?)) *(?P<cond_unit>((([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]
?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉)|[Mk]?Hz)[/a-z0-9]{0,4}){0,2})?|([a-z]
{1,2}([/a-z0-9]*|[_ ][a-z]{1,3})(\([a-z0-9]{1,6}\))?)) *[-+*/]? *)+( +to +(?P<cond_val_to>(-?[0-9]+(\.[0-9]+)?)) *(?P<
cond_unit2>([uμnm]s|㎱|㎲|㎳)|[uμnp]F|[m]?Vv?|[uμnp]?C|[muμn]?A|[mkM]?(Ω|Ω|O|Q|Ohm|W)|[k]?(S)|(°C|℃)/W|(°[CF]|K|℃|℉)|[Mk]
?Hz)?)? *[;,\n ]*)+[-    _.,;:#*"\'()\[\]a-z0-9]*\n)?(?P<min>[-~=._]+|nan|[0-9]+(\.[0-9]+)?)\n(?P<typ>[0-9]+(\.[0-9]+)?)
\n(?P<max>[-~=._]+|nan|[0-9]+(\.[0-9]+)?)\n(\n|$)' in 'Ciss\nCoss\nCrss\nVGS=0V ,
f=1MHz\nCiss=Cgs+Cgd\nCoss=Cds+Cgd\nCrss=Cgd\nVDS=520V\nVDS=325V\nVDS=130V\nFigure 10 Typical Theshold Voltage vs
Junction Temperature\nFigure 11 Typical Breakdown Voltage vs Junction Temperature'
causes catastrophic backtracking on this input:
input="""Ciss
Coss
Crss
VGS=0V , f=1MHz
Ciss=Cgs+Cgd
Coss=Cds+Cgd
Crss=Cgd
VDS=520V
VDS=325V
VDS=130V
Figure 10 Typical Theshold Voltage vs Junction Temperature
Figure 11 Typical Breakdown Voltage vs Junction Temperature"""

can you fix the regex?
