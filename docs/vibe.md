
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

*