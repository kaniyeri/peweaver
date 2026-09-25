# Allen Neuropixels fixed-stimulus plan

Status: planned provenance contract; no Allen data is stored in this repository.

## Purpose and claim boundary

Use a small, pinned excerpt of the Allen Visual Behavior Neuropixels release as
representative neural-activity stimulus for PEWeaver's RTL regressions and
switching/activity analysis. This makes the hardware demonstration concrete and
reproducible. It does **not** measure, train, or claim movement-intent,
seizure-prediction, clinical, or BCI-task accuracy: the release is mouse visual
behavior data, not a seizure or implanted-BCI ground truth set.

## Fixed-vector recipe

1. Pin one Allen release manifest, one `ecephys_session_id`, one probe/region
   selection, and absolute time windows. Store source URL, manifest version,
   session identifier, SHA-256 of the downloaded input, and extraction-tool
   version outside Git in the run record.
2. From spike-sorted unit timestamps, construct a deterministic population-rate
   sequence: count selected units in fixed 1 ms bins, then apply a documented
   integer scale and saturate to signed 16-bit samples. The selector, bin width,
   sorting rule, scale, and saturation policy are immutable per vector pack.
3. Split a bounded prefix into `stimulus_input.json` (or a compact text/hex
   format) committed only when redistribution terms and size permit. Retain a
   hash and regeneration recipe in all cases.
4. Generate `golden_threshold.json` and `golden_fft.json` using versioned
   bit-accurate software reference models. Golden output includes every valid
   sample, ordering, fixed-point scaling/rounding/overflow behavior, and
   expected latency; never hand-author expected values.
5. Make Verilator drive exactly the quantized input stream and compare every
   output to the golden stream. The same input sequence supplies VCD activity
   later for matched-input power estimation.

## Minimum provenance record

```json
{
  "dataset": "Allen Visual Behavior Neuropixels",
  "release_manifest_url": "<versioned S3 manifest URL>",
  "ecephys_session_id": "<integer>",
  "selection": {"probe": "<id>", "region": "<acronym>", "unit_filter": "<rule>"},
  "time_windows_seconds": [[0.0, 1.024]],
  "bin_width_us": 1000,
  "quantization": "signed Q-format and saturation rule",
  "source_sha256": "<sha256>",
  "extractor_revision": "<git hash>",
  "golden_sha256": "<sha256>"
}
```

## Scope control

Start with metadata plus one selected session, not a bulk cache. Allen's
documentation states that the full Visual Behavior Neuropixels release contains
153 NWB files and requires about 524 GB. The loader/extractor belongs to the
later data-preparation environment; the local RTL toolchain consumes only the
frozen, small vector pack and provenance record.
