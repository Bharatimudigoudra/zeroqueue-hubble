# Retrieval latency benchmark

Date: 2026-09-22
Questions: 15

Measured around retrieval only. The Moss index was loaded into memory before timing; index creation, model download, answer generation, and network setup are excluded.

| Retriever | p50 | p95 |
|---|---:|---:|
| Moss in-process hybrid search | 10.3 ms | 16.79 ms |
| Previous local keyword scorer | 53.56 ms | 66.5 ms |

Moss sub-10ms p95 result: **NOT MET**

| Question | Moss ms | Local ms | Moss top brand | Local top brand |
|---|---:|---:|---|---|
| How do I redeem an Amazon gift card? | 24.00 | 53.59 | Amazon shopping | Reliance Smart |
| What is the validity of a Zepto voucher? | 11.20 | 54.70 | Zepto | Amazon shopping |
| Can I exchange a gift card for cash? | 9.60 | 49.91 | Amazon shopping | Reliance Smart |
| Where can I use a Myntra gift card? | 11.50 | 52.50 | Myntra | Reliance Smart |
| What discount is available on Swiggy? | 9.00 | 43.84 | Foxtale | Reliance Smart |
| Can I use an Apollo Pharmacy voucher online? | 9.50 | 53.56 | Apollo | Reliance Smart |
| How do I redeem a Croma gift card in a store? | 12.70 | 50.18 | Croma | Reliance Smart |
| Does a MakeMyTrip gift card expire? | 9.30 | 54.41 | MakeMyTrip Bus | Reliance Smart |
| Can I combine gift cards for one purchase? | 9.10 | 49.15 | Veridicus | Reliance Smart |
| What happens if my order costs more than the voucher? | 10.40 | 64.83 | Kama Ayurveda | Fab Hotels |
| Is the gift card refundable? | 7.90 | 57.52 | Joyalukkas Diamond | Reliance Smart |
| Can I use a voucher during a sale? | 9.40 | 52.11 | Apple Premium Reseller | Amazon shopping |
| How do I add an Amazon voucher in the app? | 11.80 | 59.79 | Amazon shopping | Amazon shopping |
| Where do I find the gift card PIN? | 13.70 | 70.38 | IKEA | Reliance Smart |
| Can an expired voucher be extended? | 10.30 | 44.39 | Apollo | Amazon shopping |
