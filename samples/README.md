# Sample telemetry

Small invented files for the parser tests. They are not real satellite data.

A gap is two neighboring samples separated by more than twice the median positive sampling interval. The multiplier is configurable. The default is 2. Duplicate timestamps are ignored when the median is computed.

The gap window starts at the last sample before the hole and ends at the next sample. Times are converted to UTC before that comparison.

| File | What it shows | Gaps |
|---|---|---|
| `telemetry/steady.csv` | A sample every 10 seconds | none |
| `telemetry/one-gap.csv` | Same 10-second cadence, then a 60-second hole | `2026-03-01T00:00:30Z` to `2026-03-01T00:01:30Z` |
| `telemetry/mixed-zones.json` | Offsets `-05:00` and `Z` on the same timeline, then a 90-second hole | `2026-03-01T05:00:30Z` to `2026-03-01T05:02:00Z` |

`one-gap.csv` includes the marker `DO-NOT-LOG-7f3a` in a column the parser ignores. Tests check that this marker never appears in logs.

Upload the file with the presigned POST from `POST /uploads`. CSV uses `contentType: text/csv`. JSON uses `application/json`. The object key is chosen by the API. The original filename is not used.
