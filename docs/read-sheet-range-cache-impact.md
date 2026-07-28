# What the stale `read_sheet` cache was actually hiding: nothing

Measured 2026-07-27/28, after `758b2427` added `sheet_derivation_salt` and the
follow-up commits extended it to `parse.py`, `pipeline.py` and the nested
`pdf_to_ascii` cache.

## The worry

`befbb355` changed `parse_cond_str` so a swept range reads its endpoint rather
than its false lower bound (`VGS=0to10V` → 10 V, not 0 V). `read_sheet` is

```python
@disk_cache(ttl='999d', file_dependencies=[0], hash_func_code=False,
            salt=('v11', field_repr_salt))
```

`hash_func_code=False` means the key never saw the function body, and
`field_repr_salt` covers how a `Field` *stores* a value — not `pdf/sheet`, which
decides what is extracted. So every existing entry stayed valid across that
change and a cached run kept serving the pre-fix reading.

Gate-drive loss goes as `Qg·Vgs·f`, so collapsing the 4.5 V and 10 V gate-charge
rows onto one another is a 2x error in a ranked quantity, delivered by a cache
HIT with nothing looking wrong. Once the salt invalidates those entries the next
run re-derives them, and the concern was that values would move with no
explanation.

## The measurement

Arm A monkeypatches `parse_cond_str` with its `befbb355~1` source, read out of
git and exec'd against the live module globals. Arm B is HEAD. Disk cache
disabled in both; nothing on disk is swapped, so a peer agent can commit while
it runs. The patch is calibrated before use — it asserts the old function
reproduces `VGS=0to10V → {'Vgs': 0.0}`, so arm A cannot silently measure current
code twice.

Two samples, because the first was too weak to conclude from:

| sample | parts | entries | moved |
|---|---|---|---|
| random | 11 | 222 | 0 |
| selected for containing a glued/unspaced range | 9 | 114 | 0 |

The random draw alone was **not** evidence of no effect: `befbb355` measured
~18% of parts affected on v2, so ~2 changes were expected in 11 and seeing 0 has
roughly a 10% probability. The second sample targets the population the change
can reach — parts whose text contains `VGS=0to10V`, `VDS = 0V to 44V`,
`TJ = 25C to 150C`.

## Why it is zero

`read_sheet` never extracts the rows that carry the ranges. On the four parts
whose gate-charge rows contain `VGS=0to<n>V`:

```
IQD005N04NM6CG        5 entries: Id, Qg, Qoss, Rds_on, Vds
BSC220N20NSFDATMA1    5 entries: Ciss, Id, Rds_on, Vds
BSZ0902NSATMA1        4 entries: Id, Rds_on, Vds
BSZ096N10LS5ATMA1     4 entries: Id, Qoss, Rds_on, Vds
```

`Qgs` is absent from all four, and the swept range lives on the gate-charge
rows. You cannot serve a stale wrong value for a row you never parsed.

Note the recall: 4–5 fields where v2 recovers 14–24 on comparable parts. That is
the same asymmetry the method-domination study found when v2 replaced
`read_sheet` in the pipeline, and it is the whole reason this cache hole was
harmless in practice.

## What this does and does not license

The salt is still correct and worth keeping: a helper-only edit in `pdf/sheet`
genuinely was invisible to the cache, and that is a live hazard for any future
change to a symbol `read_sheet` *does* extract. What is now measured is that it
has **no retroactive effect on this corpus** — no DB value moves because of it.

Limits, stated rather than implied: 20 parts total, `read_sheet` costs
30–360 s/part so a corpus-wide run is hours, and the selection was drawn from a
400-part scan for the textual construct. A part whose range sits on a symbol
`read_sheet` does extract would move, and none was found.

## Method notes worth keeping

* **Never snapshot-and-restore a shared file for an A/B.** The first version of
  this harness did, HEAD moved under it while a peer committed three times, and
  the restore reverted their work. Patch in memory instead.
* **Write results incrementally.** The previous run dumped JSON only at the end,
  hit a timeout after 6 of 9 parts, and lost everything.
* **Back-to-back `read_sheet` arms are not time-comparable.** Arm A ran 2–5x
  slower than arm B on identical parts (363 s vs 46 s on one) — warm page cache
  and already-fetched font mappings. Outputs are comparable; timings are not.
* **A zero-delta A/B needs the instrument checked before it is interpreted.**
  Both null results here are trustworthy only because the patch was calibrated
  to reproduce the old behaviour first.
