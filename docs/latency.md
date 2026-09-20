# Retrieval latency benchmark

Date: 2026-09-20
Questions: 15

Measured around retrieval only. The Moss index was loaded into memory before timing; index creation, model download, answer generation, and network setup are excluded.

| Retriever | p50 | p95 |
|---|---:|---:|
| Moss in-process hybrid search | 11.0 ms | 21.87 ms |
| Previous local keyword scorer | 52.37 ms | 66.05 ms |

Moss sub-10ms p95 result: **NOT MET**

| Question | Moss ms | Local ms | Moss top brand | Local top brand |
|---|---:|---:|---|---|
| How do I redeem an Amazon gift card? | 22.50 | 56.58 | Amazon shopping | Amazon shopping |
| What is the validity of a Zepto voucher? | 21.60 | 68.33 | Zepto | Zepto |
| Can I exchange a gift card for cash? | 12.40 | 65.07 | Amazon shopping | Powersutra |
| Where can I use a Myntra gift card? | 13.50 | 51.46 | Myntra | Myntra |
| What discount is available on Swiggy? | 8.70 | 45.96 | Foxtale | Xfused |
| Can I use an Apollo Pharmacy voucher online? | 9.10 | 45.84 | Apollo | Apollo |
| How do I redeem a Croma gift card in a store? | 11.80 | 52.05 | Croma | Croma |
| Does a MakeMyTrip gift card expire? | 11.60 | 52.37 | MakeMyTrip Bus | Brooks Brothers-Luxe Gift Card |
| Can I combine gift cards for one purchase? | 9.90 | 55.65 | Veridicus | Veridicus |
| What happens if my order costs more than the voucher? | 10.50 | 61.37 | Kama Ayurveda | Naturals Salons |
| Is the gift card refundable? | 10.90 | 54.19 | Joyalukkas Diamond | Uber Gift Voucher |
| Can I use a voucher during a sale? | 9.70 | 46.99 | Apple Premium Reseller | Croma |
| How do I add an Amazon voucher in the app? | 11.00 | 46.16 | Amazon shopping | Amazon shopping |
| Where do I find the gift card PIN? | 9.00 | 59.01 | IKEA | Apple Premium Reseller |
| Can an expired voucher be extended? | 12.40 | 48.33 | Apollo | Powersutra |
