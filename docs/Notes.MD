# New approach

5 doc types:

- text as pdf, table grid vectors
- text in pdf but broken enconding, tables grid vectors
- vectorized text (need OCR), tables grid vectors
- rasterized pdf
- scanned pdf (very rare)


1. detect tables and their bbox using (vector data or OCR)
2. detect the table cells. consider borderless tables and implicit rows and columns (no lines)
3. unwrap merged cell content (colspan, rowspan)
4. iterate rows
    5. iterate cells (columns).
    6. if column text is empty, do OCR (aware of subscript, symbols units, SI-prefix, formulars, math operators)

- find a tabular segmentation with merged cells
    - some tables have missing borders
    - apps
        - https://github.com/jsvine/pdfplumber
        - tabula
        - tesseract with tables (TODO link)
        - pix2image
    -

img2table does a good job on rasterized tables.
it is useful to add borders to tables and draw implicit row/column grid.

pdf2plumber and pymudf are similar.
they work good with table grid vectors. does they work with rasterized?

- todo string normalisation

# Power Loss Model

The power loss model for a DC-DC buck is based on this rOHM article. We assume CCM mode, coil current never touches
zero.
Note that loss from LS reverse recovery `P_rr` is dissipated in HS. In other words, bad behaviour of LS heats up the HS.
The generated CSV file includes the estimated losses caused by a transistor when placed in the HS or LS slot.
Note that this power is not necessarily dissipated in the same switch.

# DCDC

In a buck converter, the high-side switch is desirably fast (low Q_d, r_g) and has low Rds_on.
The LS sync fet operates in a rather different way, parasitic turn-on can become a problem here.
Because we make use of the body diode, reverse recovery charge can cause high current peaks increasing losses in the HS
switch and input capacitor.
this [eetimes article](https://www.eetimes.com/how-fet-selection-can-optimize-synchronous-buck-converter-efficiency/)
gives a good overview.
https://github.com/fl4p/Fugu2/blob/main/doc/Mosfets.md

Most part suppliers have a parametric search function that is just good enough.
We can usually filter and sort by `Vdss`, `Id`, `Qg`, `Rds_on`.
For some specific applications we might want to filter more parameters that we can only find in the datasheet, such
as `Qrr`.

# Ranking mosfets

synchronous DC-DC converter

* Conduction loss (Rds_on)
* Switching losses (tRise+tFall)
* Reverse recovery losses (Qrr)
* Gate drive losses

According to
the [Rohm AN](https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/power_loss_appli-e.pdf),
high-side (control fet) switching losses are ~= C * (tRise + tFall) with C=0.5 * V_in * I_o * f_sw.

To rank MOSFETS, we can come up with a FoM like
Rds_on * Qrr * (tRise+tFall)

To reduce gate drive current and loss:
Rds_on * Qgd * Qrr * (tRise+tFall)

# Mosfet FOM

FOM (Figure of Merit) is a common performance indicator to rank MOSFET power loss for DC-DC converter applications.
Our aim is to reduce total mosfet loss:

```
P_mosfet = Pon + Psw + Prr + Pgd
Pon = A * Rds           # A ~ Io * Vo/Vi
Psw = B * (tRise+tFall) # B ~ Vin * Io * f
Prr = C * Qrr           # C = Vin * f
Pgd = D * Qg            # D ~ Vgs^2 * f

P_mosfet = A * (Rds) + B * (tRise+tFall) + C * (Qrr) + D * (Qg)
```

It tries to indicate a score about how efficient the MOSFET is in a switching app (the lower the better).

```
FOM = Rds_on * Qg
```

Yoo et al propose a new FOM [[2007, link](https://sci-hub.se/10.1109/EDSSC.2007.4450305)]:

```
FOM_new = (Il²) * Rds_on  +  (4 * fs * Vgg) * Qg`
```

* `Il`: average load current
* `fs`: switching frequency
* `Vgg`: gate driver supply voltage

However, with modern high-current gate drivers, low `Qg` becomes less important.
High-efficiency converter use fast switching times and `Qrr` becomes more
important [src](https://efficiencywins.nexperia.com/efficient-products/qrr-overlooked-and-underappreciated-in-efficiency-battle)

Note that GaN-switches have a `Qrr` of zero.

To find the best chip for a specific app, we can define our own custom scores, such as:

* `Rds_on * Qg / Vds`
* `sqrt(Rds_on * Qg * Qrr)`
* `Rds_on * Qrr`
* `Rds_on * Qrr * Qg * (t_rise+t_fall)`

In a half-bridge topology for synchronous DC-DC converters the HS and LS switch work in quite different
conditions. Current through the LS usually flows from Source to Drain in the direction of the body diode. It acts as a
synchronous rectifier aka. ideal diode

### Special Qrr Datasheets

* 'PSMN4R2-80YSEX': Qrr timing plot
* UM1575 User manual spice models
* PSMP050N10NS2_T0_00601: Vplateau
* IPA050N10NM5S : Vplateau

## Qg_th

- csd19506
- BSB056N10NN3: typo, Gate to drain charge confusion

# Coss power loss

* Use ocr (sample 'BUK7E4R0-80E,127.pdf', 'IPB019N08N3GATMA1' ) `ocrmypdf` can recover the text, but doesn't recognize
  symbols
  correctly.
* Mouser, API?
* Extract more fields
    * Qgd/Qgs (self turn on)
    * Vsd (body diode forward voltage)
    * r_g

# Resources

* https://www.discoveree.io/
* https://octopart.com/ (Ciss, rise&fall times, )
* https://epc-co.com/epc/design-support/part-cross-reference-search
    * a very useful tool that comes with power loss calculations. i found some values to be off, e.g. IPA050N10NM5S
      Rds_on_max@10V is 5, in the app its 5.6.

https://www.discoveree.io/collateral/continental/PCIM2020_DiscoverEE_PowerLossModeling_AudioVisual.mp4
https://www.discoveree.io/collateral/PCIM_Europe_2020/PCIM2020_DiscoverEE_PowerLossModeling_Slides.pdf
https://pcimasia-expo.cn.messefrankfurt.com/content/dam/messefrankfurt-redaktion/pcim_asia/download/pac2020/speakers-ppt/1/Shishir%20Rai.pdf
https://ww1.microchip.com/downloads/en/Appnotes/01471A.pdf
https://www.st.com/resource/en/application_note/dm00380483-calculation-of-turnoff-power-losses-generated-by-a-ultrafast-diode-stmicroelectronics.pdf
https://www.vishay.com/docs/73217/an608a.pdf

# names

fetlib
mosfetlib
fetfinder
findfet
mosdb

# Tabula CMD

```
["java" "-jar" "~/dev/tabula-java/target/tabula-1.0.6-SNAPSHOT-jar-with-dependencies.jar",
                            "--guess",
                            "--pages", "all",
                            '""']
                            
java-jar~/dev/tabula-java/target/tabula-1.0.6-SNAPSHOT-jar-with-dependencies.jar --guess --pages all                            
```

# PDF Documents

Text in PDF Documents consist of characters (chars) (letters, numbers ...) located at a point and within a bounding box.
Tables are usually constructed by one or multiple vector path elements. There is no systematic representation like in
HTML or Markdown. Text elements contain the actual content string and are rasterized with a system or embedded font.

Think of pdf files as a HTML document with a div-element for each single character that have `position: absolute`,
without any inherent relations to each other apart from location proximity. This ensures pixel-perfect rendering, even
if one character in a fluent text is not rendered properly due to enconding issues. PDF does not "know" whitespaces,
because it doesn't need them. However, some PDF producer software, even Acrobat Distiller, appears to ignore this fact
and places ' ' (space, U+0020) chars even when they render to a non-printable SPACE (CID Fonts or Custom Encoding might
map U+0020 to an actual printable glyph, so that might be the reason they are not discarded from the final PDF).

It is up to the reader to assemble fluent text from the individual characters.

* TODO text strings are not used for rendering ! https://stackoverflow.com/questions/128162/unicode-in-pdf

## PDF Tools overview

* pymupdf (wraps C mupdf)
    * no user control of text blocking
    * fast C implementations for pdf object iterations
* pdfminer.six
    * user has control on text blocking
* pdfplumber
    * < `pdfminer.six`
    * < `pypdfium2`
* `ocrmypdf`
    * < `img2pdf` < `pikepdf`
    * < `pdfminer.six`
    * tesseract wrappers
* `afdko` [git](https://github.com/adobe-type-tools/afdko/)
    * has [tools](https://adobe-type-tools.github.io/afdko/AFDKO-Overview.html) for working with CFF Type1
      Fonts (`type1/detype1`)  and proofing (`charplot`)
* `pdf.js`

* pdf2image (wraps pdftoppm)

Table Extraction

* tabula (JAVA, tabula web)
* camelot (< `pdfminer`)
* pix2text
* img2text
  `tabula`, `pymupdf`, `pdfplumber`, `pix2text` and `img2table`.
  Fonts

* `pdffonts ../datasheets/onsemi/NTMFSC4D2N10MC.pdf` (originally from Xpdf, now part of Poppler)

Charset Encoding Tools

* `charset-normalizer` (reads text from an unknown encodnig)
* python built-in `unicodedata`

## pdfminer.six

Reads: [pdfminer.six/pdf to text](https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html)

**LAParams:**

* `char_margin` threshold for grouping chars to words
* `word_margin` threshold for grouping words to lines (insert space char, *pdf has no space character*)
* `line_overlap` vertical threshold for line grouping
* `line_margin` vertical threshold of grouping lines into boxes/blocks/paragraphs

To summarize, a text block consists of 'lines', each line contains 'spans', which carry the
style information. Each 'span' consists of 'words', and 'words' of 'chars'.
The whole hierarchy is : `doc > page > block > line > span > word > char`.
Notice that we know the bounding boxes (bbox) of each character relative to the page origin.

# TODO https://github.com/fl4p/fetlib/issues/28

A docu

# Char margin

- subscript in symbols like Q_gd can fall into a new line if `line_overlap` is too high. TODO write test
  NTMFSC4D2N10MC:
- ![img_1.png](NTMFSC4D2N10MC_Qg.png)
- ![img_1.png](img_1.png)
- ![img_2.png](img_2.png)
- Remember that PDF has no fluent text, just individual chars at absolute positins. Subscript chars just are just a bit
  lower.
- with `line_overlap=0.5` this renders to `"Q\nG(TOT)"`,
- `line_overlap=0.3` results  `"QG(TOT)"`,

![img_3.png](IPA029N06NXKSA1_3.png)
^in between lines "Drain-source on resistance"

## pymupdf (wraps mupdf C code)

PyMupdf does not offer an API for setting parameters during text block creation.

* [Set space threshold to decide text blocks #1358](https://github.com/pymupdf/PyMuPDF/discussions/1358)
* [General structure of a TextPage](https://pymupdf.readthedocs.io/en/latest/app1.html#general-structure-of-a-textpage)

Depending on the PDF creator software, the hierarchy can carry some information of the logical structure of content,
however we can't rely on this because some software use wierd optimization techniques that merge rather unrelated but
positionally close
content into the same block.

You can visually inspect the blocks structure with [vectorpea](https://www.vectorpea.com/) .

pymupdf has methods in the `TextPage` class for deep data structure inspection down to text char level:

* `.extractBLOCKS()` position, text content and type
* `.extractWORDS()` word bbox and text block, line and number
* `.extractDICT()`  style information (font, color), direction, line
  height  [see here](https://pymupdf.readthedocs.io/en/latest/textpage.html#textpagedict)
* `.extractRAWDICT()` positioning on char level

Some PDF (BSC050N10NS5ATMA1, Power PDF Create) have text rendered as vector paths, combined with surounding table
structure.
To convert these paths into text strings, need to rasterize to image and do OCR. Care must be taken with the
rasterization method,
as OCR works best without interpolation, rather grainy characters? Also very high DPI (>800?) can cause troubles.

Rasterization with pdf2image rather than pymupdf led to better OCR performance (200-600 DPI) in my tests.

we need to think about how to mine the data under these considerations:

* no formal representation of tables
* some datasheets are completely rasterized to images or contain just vector text
* diversity of document structure across manufacturers

Datasheets are made for humans, not machines. Sometimes tables omit units that we can easily imply from previous
information (e.g. Q is usually nC).
Converting the PDF to a text string discards 2D information. With regex we can extract data for well structured PDFs,
but still information might leak from neighbouring rows/columns because the regex parse has no clue if the next number
is still in the same row. The test condition column might be placed between symbol and value columns and the arbitrary
format can easily lead to confusion of numeric values.

I tested table extraction with `tabula`, `pymupdf`, `pdfplumber`, `pix2text` and `img2table`.

* `tabula` has issues with detecting relevant tables. It detects frames around page content (EPC sheets) as tables and
  cannot properly process nested tables. Lattice and Stream method, Stream appears to work better on unsupervised
  datasheet extraction. Does not work with rasterized PDF / images.
* `pymupdf` and `pdfplumber` are similar. `pymupdf` has parts written in C. They have horizontal strategy
  options `f{lines,lines_strict,text,explicit}`.
* pymupdf *extractHTML()* doesn't support tables
* Parameters for snapping, joining, intersecting and text spacing exists, see
  Page.[find_tables](https://pymupdf.readthedocs.io/en/latest/page.html#Page.find_tables).

![img.png](img.png)

In the proposed approach we forget about the table structure, instead we just care about identifiying header and symbol
texts.
With the coordinates and bounding boxes of the identified elements we can project the position of potential value cells.
E.g. project the "Typ" column x0-x1 width downwards and the symbol row height y0-y1 to the left. the intersection of
these 2 projections is expected to contain the typical value for this symbol.

We can extract the text blocks:

```
pdf = pymupdf.open("datasheets/infineon/2N7002DWH6327XTSA1.pdf")
for pg in pdf.pages():
    tpg = pg.get_textpage()
    for x0, y0, x1, y1, text, num, typ in tpg.extractBLOCKS():
        print(pg.number, num, typ, repr(text))
```

```
2 0 0 '2N7002DW\n'
2 1 0 'Parameter\nSymbol Conditions\nUnit\n'
2 2 0 'min.\ntyp.\nmax.\n'
2 3 0 'Dynamic characteristics\n'
2 4 0 'Input capacitance\nC iss\n-\n13\n20\npF\n'
2 5 0 'Output capacitance\nC oss\n-\n4.1\n6\n'
2 6 0 'Reverse transfer capacitance\nCrss\n-\n2.0\n3\n'
2 7 0 'Turn-on delay time\nt d(on)\n-\n3.0\n4.5\nns\n'
2 8 0 'Rise time\nt r\n-\n3.3\n5\n'
2 9 0 'Turn-off delay time\nt d(off)\n-\n5.5\n9\n'
2 10 0 'Fall time\nt f\n-\n3.1\n5\n'
```

notice:

* the end-of-lines '\n' for horizontal seperation.
* nested merged cells (testing conditions) appear more below
* 'Headers': 2 1 0 'Parameter\, Symbol Conditions\,Unit\n' 2 2 0 'min.\ntyp.\nmax.\n', and the `Values`
* `Symbol` and `Conditions` share the same line

Replacing '\n' with ',' already gives us some sort of CSV table:

| C1                              | C2                | C3   | C4   | C5   | C6   |
|:--------------------------------|:------------------|:-----|:-----|:-----|:-----|
| Parameter                       | Symbol Conditions | Unit | null | null | null |
| min.                            | typ.              | max. | null | null | null |
| Dynamic characteristics         | null              | null | null | null | null |
| Input capacitance               | C iss             | -    | 13   | 20   | pF   |
| Output capacitance              | C oss             | -    | 4.1  | 6    | null |
| Reverse transfer capacitance    | Crss              | -    | 2.0  | 3    | null |
| Turn-on delay time              | t d\(on\)         | -    | 3.0  | 4.5  | ns   |
| Rise time                       | t r               | -    | 3.3  | 5    | null |
| Turn-off delay time             | t d\(off\)        | -    | 5.5  | 9    | null |
| Fall time                       | t f               | -    | 3.1  | 5    | null |
| Gate Charge Characteristics     | null              | null | null | null | null |
| Gate to source charge           | Q gs              | -    | 0.05 | 0.1  | nC   |
| Gate to drain charge            | Q gd              | -    | 0.2  | 0.4  | null |
| Gate charge total               | Q g               | -    | 0.4  | 0.6  | null |
| Gate plateau voltage            | V plateau         | -    | 4.0  | -    | V    |
| Reverse Diode                   | null              | null | null | null | null |
| Diode continous forward current | I S               | -    | -    | 0.3  | A    |
| Diode pulse current             | I S;pulse         | -    | -    | 1.2  | null |
| Diode forward voltage           | V SD              | null | null | null | null |
| V GS=0 V; I F=0.5 A;            | T j=25 °C         | -    | 0.96 | 1.2  | V    |
| Reverse recovery time           | t rr              | -    | 8.5  | 13   | ns   |
| Reverse recovery charge         | Q rr              | -    | 2.4  | 4    | nC   |
| V R=30 V; I F=0.5 A;            | di F/dt =100 A/µs | null | null | null | null |
| T A=25 °C                       | null              | null | null | null | null |

When we change the print line to:

```
print(pg.number, num, typ, ' ' * int(x0/10) + text.replace('\n', '\t'))
```

we get this:

```
2 0 0                                                2N7002DW	
2 1 0      Parameter	Symbol Conditions	Unit	
2 2 0                                       min.	typ.	max.	
2 3 0      Dynamic characteristics	
2 4 0      Input capacitance	C iss	-	13	20	pF	
2 5 0      Output capacitance	C oss	-	4.1	6	
2 6 0      Reverse transfer capacitance	Crss	-	2.0	3	
2 7 0      Turn-on delay time	t d(on)	-	3.0	4.5	ns	
2 8 0      Rise time	t r	-	3.3	5	
2 9 0      Turn-off delay time	t d(off)	-	5.5	9	
```

when we continue to compute horizontal position based on first-word of 'cell':

```
    tpg = pg.get_textpage()
    for block in tpg.extractDICT()["blocks"]:
        row = ""
        for line in block['lines']:
            span_text = ''.join(s['text'] for s in line['spans'])
            row += ' ' * (max(1, int(line['bbox'][0]/5)-len(row))) + span_text
        print(row)
```

we end up with this neat output:

```
                                                                                              2N7002DW
           Parameter                         Symbol Conditions                                      Unit
                                                                            min.     typ.    max.
           Dynamic characteristics
           Input capacitance                 C iss                            -       13      20    pF
           Output capacitance                C oss                            -       4.1      6
           Reverse transfer capacitance      Crss                             -       2.0      3
           Turn-on delay time                t d(on)                          -       3.0     4.5   ns
           Rise time                         t r                              -       3.3      5
           Turn-off delay time               t d(off)                         -       5.5      9
           Fall time                         t f                              -       3.1      5
           Gate Charge Characteristics
           Gate to source charge             Q gs                             -      0.05     0.1   nC
           Gate to drain charge              Q gd                             -       0.2     0.4
           Gate charge total                 Q g                              -       0.4     0.6
           Gate plateau voltage              V plateau                        -       4.0      -    V
           Reverse Diode
           Diode continous forward current   I S                              -        -      0.3   A
           Diode pulse current               I S,pulse                        -        -      1.2
           Diode forward voltage             V SD
                                                      V GS=0 V, I F=0.5 A,  T j=25 °C - 0.96  1.2   V
           Reverse recovery time             t rr                             -       8.5     13    ns
           Reverse recovery charge           Q rr                             -       2.4      4    nC
                                                      V R=30 V, I F=0.5 A,  di F/dt =100 A/µs
                                                      T A=25 °C
                                                                                    Values
                                                      V GS=0 V, V DS=25 V,  f =1 MHz
                                                      V DD=30 V, V GS=10 V,  I D=0.5 A, R G,ext=6 W
                                                      V DD=48 V, I D=0.5 A,  V GS=0 to 10 V
           Rev.2.3                                      page 3                                   2014-09-19
```

Notice:
`Values` headers appears at the bottom
that some of the test condition are placed after the table and the column doesn't even

# Flux AI

* to talk to Copilot Assistan you need to sign in and open a project.
* before it was possible to send links to PDF files in the chat
* posting screenshots of datasheet tables generates garbish data

# Tools

- vectorpea: edit text, move elements
- evince (ubuntu default PDF viewer): view information about embedded fonts (mac port exists)

```
# pip install pdfminer.six
 pdf2txt.py -o test.html -t html -Y normal  datasheets/infineon/2N7002DWH6327XTSA1.pdf
 pdf2txt.py -o test.html -t html -Y exact  datasheets/infineon/2N7002DWH6327XTSA1.pdf # layout on char level
  pdf2txt.py -o test.html -t html datasheets/toshiba/TK35A08N1.pdf # table grid good, but text not aligned
    pdf2txt.py -o test.html -t html  -Y exact datasheets/toshiba/TK35A08N1.pdf # table grid good, but text not aligned
 
 
 
 ```

# Fonts

You will often find PDFs with embedded fonts for special (unicode) symbols (glyphs) such as µ Ω ϴ.
These embedded fonts are either a subset font, or a CID font. The binary data of the font (mostly TrueType or OpenType)
reside inside the PDF file and can be extracted. OpenType Type1 `.cff` can be difficult to read, as they use a sftn
version
which browsers and other tools do not understand. Use Fontforge for conversion.

```
# https://adobe-type-tools.github.io/afdko/AFDKO-Overview.html
charplot HGIKGE+IntDutch801G-Roman.otf 
charplot -g cid0002 HGIKGE+IntDutch801G-Roman.otf 


# poppler pdffonts
pdffonts ../datasheets/onsemi/NTMFSC4D2N10MC.pdf
```

https://shapecatcher.com/