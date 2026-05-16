
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
Vpl valid range is (-1, 10).

Write a program that finds the Gate Charge Curve chart in a PDF and determines Vpl.
Notice the different styling of the charts across manufactureres. The curves look all quite similar.
Use sample files from test/tests.py. Some reference data includes Vpl, which you can use to validate your program.
Put your code in viz/.

Find charts by their caption with this regular expression (case insensitive):
r"(([0-9]*\s*typ(\.|ycal)\s+)?gate[\s-]+charge\s+(curve|vs|waveforms?).*|(Fig.?(ure)?)\s*[0-9]+\s*[.:]\s*Gate[\s-]
+Charge.*)"

Are there any captions you have seen in the text that you might think should match? e.g. using synonyms for "curve" or
"diagram"? then optimize the regex to match these synonyms



* the chart in BSB056N10NN3GXUMA2.pdf is rastered with a caption "14 Typ. gate charge". at caption based chart detection
  with regex for matching similar captions
* in BSZ084N08NS5ATMA1.pdf there are actually 3 curves hardly distinguishable from each other. The curves have small
  labels next to them. Ignore the labels as they might interfere with finding the plateau.
* take a look at st/STB55NF06LT4.pdf . here the chart is inside a wireframe box, and the caption is above the
  box
* the chart in NVTFWS010N10MCLTAG.pdf has Dimension lines with arrow termination, labeled Qgs and Qgd. Ignore these. 

* AOMR62818 has a genuinely smooth knee — no horizontal plateau exists in
   the chart. The detector correctly returns None rather than picking a wrong row. The previous wrong 7.14 V is
  now an honest miss; recovering the implied 3.0 V would need an inflection-point algorithm (look at d²V/dQ²),
  which is a different approach altogether.
  * datasheets/ao/AOT286L.pdf
  * datasheets/ao/AOTL66518Q.pdf
  * datasheets/ao/AOB284L.pdf
* Ignore charts labeled: "Gate charge waveform definitions", "Source Drain Diode Forward Voltage", "Switching Time Test Circuit". The space between these words might be dashes, so use regex. 


datasheets/ao/AOT286L.pdf

```
{
  "datasheets/agmsemi/AGM15T13D.pdf": {
    "ref": 4.2,
    "comment": "line has a bright blue"
  },
  "datasheets/ao/AOMR62818.pdf": {
    "ref": 3,
    "comment": "the plateau starts smoothly"
  },
  "datasheets/ao/AOT286L.pdf": {
    "ref": 4.2,
    "comment": "the line has noise"
  },
  "datasheets/infineon/IPW65R019C7.pdf": {
    "ref": 5.4
  },
  "datasheets/infineon/IRF540NL.pdf": {
    "ref": 4.6,
    "comment": "there is an overlapping text box \"FOR TEST...\""
  },
  "datasheets/nxp/PSMN1R2-55SLH.pdf": {
    "ref": 2.4
  },
  "datasheets/onsemi/NVMFS5C468NLT1G.pdf": {
    "ref": 3.5,
    "comment": "dimension lines with Qgs,Qgd labels"
  },
  "datasheets/onsemi/NVMYS029N08LHTWG.pdf": {
    "ref": 3,
    "comment": "dimension lines with Qgs,Qgd labels"
  },
  "datasheets/onsemi/NVTFWS010N10MCLTAG.pdf": {
    "ref": 2.6,
    "comment": "dimension lines with Qgs,Qgd labels"
  },
  "datasheets/agmsemi/AGM025N13LL.pdf": {
    "ref": 4.3,
    "comment": "rasterized"
  },
  "datasheets/agmsemi/AGM150P10AP.pdf": {
    "ref": 3.1,
    "comment": "rasterized"
  },
  "datasheets/hxy/R6509KND3TL1-HXY.pdf": {
    "ref": 8,
    "comment": "rasterized"
  },
  "datasheets/hxy/SIHD6N65ET4-GE3-HXY.pdf": {
    "ref": 2.9,
    "comment": "rasterized"
  },
  "datasheets/infineon/IAUC28N08S5L230ATMA1.pdf": {
    "ref": 3.1,
    "comment": "rasterized"
  },
  "datasheets/infineon/F3L3MR12W3M1HH11BPSA1.pdf": {
    "ref": 7.25
  },
  "datasheets/infineon/IPW60R041C6.pdf": {
    "ref": 4.1,
    "comment": "rasterized"
  },
  "datasheets/nce/NCE01P05S.pdf": {
    "ref": 2.7,
    "comment": "rasterized"
  },
  "datasheets/siliup/SP015N05GHTQ.pdf": {
    "ref": 5.1,
    "comment": "rasterized"
  },
  "datasheets/st/STL70N4LLF5.pdf": {
    "ref": 3,
    "comment": "rasterized"
  },
  "datasheets/toshiba/TK057V60Z1.pdf": {
    "ref": 5.2,
    "comment": "the chart caption is \"Dynamic Input/Output Characteristics\". the chart contains a Vds-curve too. It starts at 400V and has a sharp drop to zero right before Qg reaches the miller plateau. Ignore this curve. Also ignore the left axis, as it is labeled Vds. The right axis is the one for Vgs, which is what we are looking for"
  },
  "datasheets/htcsemi/HT100NF80ASZ.pdf": {
    "comment": "missing chart"
  },
  "datasheets/toshiba/TPN1200APL.pdf": {
    "comment": "missing chart"
  }
}
{
  "datasheets/ao/AOB284L.pdf": {
    "ref": 3.95,
    "comment": "noisy line"
  },
  "datasheets/ao/AOTL66518Q.pdf": {
    "ref": 5.5,
    "comment": "smooth knee"
  },
  "datasheets/infineon/IQDH35N03LM5SC.pdf": {
    "ref": 2.2,
    "comment": "multiple curves"
  },
  "datasheets/nxp/PSMN1R0-30YLD.pdf": {
    "ref": 2.6
  },
  "datasheets/goford/11N10.pdf": {
    "ref": 4.5,
    "comment": "rasterized"
  },
  "datasheets/huayi/HYG016N04LS1B.pdf": {
    "ref": 3.6,
    "comment": "rasterized"
  },
  "datasheets/hxy/MCU655N65FH-HXY.pdf": {
    "ref": 8.5,
    "comment": "long plateau with a slop"
  },
  "datasheets/hxy/SIHH14N65EF-T1-GE3-HXY.pdf": {
    "ref": 7.5,
    "comment": "long plateau with a slop"
  },
  "datasheets/hxy/SIS444DN-T1-GE3-HXY.pdf": {
    "ref": 3
  },
  "datasheets/nce/NCE82H140LL.pdf": {
    "ref": 4.5
  },
  "datasheets/nce/NCEP070N12.pdf": {
    "ref": 5
  },
  "datasheets/nce/NCEP1545AK.pdf": {
    "ref": 0
  },
  "datasheets/st/STB140NF75.pdf": {
    "ref": 5.9
  },
  "datasheets/crmicro/CRTT020N04N.pdf": {
    "ref": 5
  },
  "datasheets/agmsemi/AGM1075MNA.pdf": {
    "ref": 3
  },
  "datasheets/infineon/IMT65R020M2H.pdf": {
    "ref": 9,
    "comment": "plateau has slope, quite steep and a \"400V\" label (ignore)"
  },
  "datasheets/siliup/SP85N01BGHTO.pdf": {
    "ref": 0.9
  }
  
}
{
  "datasheets/goford/GT085N10MH.pdf": {
    "ref": 4.5,
    "comment": "kind of smooth"
  }
}
{
  "datasheets/hxy/IPZA65R040CM8XKSA1-HXY.pdf": {
    "ref": 5.1,
    "comment": "plateau is slope"
  },
  "datasheets/hxy/STF40N65M2-HXY.pdf": {
    "ref": 5.1
  },
  "datasheets/infineon/F4-13MXTR12C1M2Q_H11.pdf": {
    "ref": 8.5
  },
  "datasheets/infineon/IMZA40R045M2H.pdf": {
    "ref": 9
  },
  "datasheets/ti/CSD19537Q3.pdf": {
    "ref": 4.5,
    "comment": "smooth"
  },
  "datasheets/vishay/IRFIZ48G.pdf": {
    "ref": 6
  },
  "datasheets/xnrusemi/XR35N10.pdf": {
    "ref": 3,
    "comment": "light colors"
  },
  "datasheets/suzhou_good-ark_elec/SSFB3910L.pdf": {
    "ref": 3.4
  }
}
```


# optimizing
*