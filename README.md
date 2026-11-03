# Under review

Every geographic name proposal pending before the U.S. Board on Geographic Names, parsed from its
Quarterly Review Lists 450–464 (February 2023 – July 2026): 493 proposals across 47 states, 488 of
them mapped, with the proponent's own stated reasoning.

## Data

Source: [Domestic Names Committee Quarterly Review Lists](https://www.usgs.gov/us-board-on-geographic-names/dnc-review-lists).
The Board posts a new list roughly every quarter.

## Rebuild

Put the review-list PDFs in a folder as `list_<number>.pdf`, then:

```
python3 parse_bgn.py     # -> bgn_raw.json
```

Lists 442–449 use an earlier, incompatible layout and are deliberately out of scope.
See [methodology.html](methodology.html).
