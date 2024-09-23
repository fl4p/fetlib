Custom wordlist https://vprivalov.medium.com/tesseract-ocr-tips-custom-dictionary-to-improve-ocr-d2b9cd17850b

Reading tables 


brew install tesseract-lang

tesseract --help-extra
# TESSDATA_PREFIX


# TODO
`tsv — Output TSV (OUTPUTBASE.tsv).`


# tesseract tesseract/BSC070N10NS3GATMA1_QG.png stdout --user-words tesseract/mosfet.user-words tesseract.cfg

# p2t predict -l en --resized-shape 2048 --file-type pdf -i datasheets/infineon/BSC070N10NS3GATMA1.pdf -o output-md --save-debug-res output-debug
