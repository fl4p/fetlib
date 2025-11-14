update micrometals.csv:

download "Curve Fit Formulas and Values" https://www.micrometals.com/design-and-applications/design-tools/"

convert to csv:

```
import pandas as pd
df = pd.read_excel('~/Downloads/mmcurvefitcoefficientsall.xlsx')
#df = df.iloc[6:,1:] # drop head and first column
df.to_csv('mmcurvefitcoefficientsall.csv')
```