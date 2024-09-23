
# paid models
https://pix2text.readthedocs.io/zh-cn/stable/examples_en/
https://ocr.lemonsqueezy.com/
 p2t predict -l en --resized-shape 2048 --file-type pdf -i datasheets/infineon/BSC070N10NS3GATMA1.pdf -o output-md --save-debug-res output-debug --mfd-config '{"model_name": "mfd-pro", "model_backend": "onnx"}' --formula-ocr-config '{"model_name":"mfr-pro","model_backend":"onnx"}' --text-ocr-config '{"rec_model_name": "doc-densenet_lite_666-gru_large"}'


https://huggingface.co/microsoft/table-transformer-structure-recognition-v1.1-all
