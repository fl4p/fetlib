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

# mosfet details modal

add another button next to MPN that opens a modal with more information about that mosfet.
in the modal:

* an image of the part from crops/<mfr>/<mpn>/part.webp
* a table with all the part properties
* an image of the gate charge curve. gate charge curves are systematically stored under crops/<mfr>/<mpn>/qg.webp .
* a link to the pdf datasheet


* the part image in the modal has a link to the datasheet
* the mpn in the table is cut-off after 20 characters with an ellipses


# for vpl-from-chart:

* generate a script that creates the cropped charts as webp files for all parts the are in parts_db. it first tries vpc
  and then
  viz method. store the image files under crops/<mfr>/<mpn>/qg.webp
* in the webp, draw a vertical Dimension line for Vpl and horizontal for Qgs and Qgd.

* extend crop_charts.py so it will find an image of the part. this is usually on the first page of the pdf. there can be
  multiple images for housing variations and top and bottom view. crop them all together in one image. if the whole page
  is rasterized or you cannot find an image, just crop the first page.



* Fix this issue: In Chrome on iOS (iPad), when narrowing the results with the slider, many rows show blank and only reveal their values when hovered, clicked or the table scrolls.
