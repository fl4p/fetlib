PDF files can have custom font encoding where characters are mapped to non-standard unicode.
This makes basic text extraction impossible.

Write a function that fixes the encoding to standard Unicode:

* first detect if the PDF has a custom font encoding
* extract the font and create a mapping: find the visually best matching Unicode symbol for each font glyph. Limit the search to common
  glyphs used in english text and technical symbols in MOSFET datasheets. Important symbols are µ and Ω.
* replace the characters in the PDF using the mapping and replace the font with a standard font
* save the PDF and return its name

Here are two samples that have custom font encoding:
datasheets/huayi/HY3912W.pdf
datasheets/infineon/IPP057N08N3GHKSA1.pdf


use the python interpreter at /home/parallels/miniconda3/envs/crunch/bin/python3
If there is a missing software package you would like to use and you cannot install it yourself, let me know.
put your code inside pdf-enc-fix/ .


* use pdfminer?