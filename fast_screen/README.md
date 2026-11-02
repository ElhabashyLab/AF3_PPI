# Faster AF3 PPI screens on Raven

This folder describes a faster way to run large AF3 pair screens, e.g. one
protein against a whole proteome. In a benchmark against the standard
workflow (sections 6–7 of the [main README](../README.md)) it needed:

- **~3x fewer CPU core-hours for the MSAs**, with identical MSAs.
- **~1.7x fewer GPU-hours**.
- **~10x fewer SLURM jobs**.

The predicted ipTM of the true interaction stayed the same (0.81 vs 0.80).

It uses the same input CSV as the rest of the repo, and its outputs work with
[AF3_analysis.py](../AF3_analysis.py).

## Why the standard workflow is slow

In the standard workflow, every pair gets its own MSA job (CPU) and its own
prediction job (GPU). This wastes compute in three ways:

1. **The same MSAs are computed again and again.** AF3 builds the MSAs and
   templates of each chain on its own, independent of the partner chain.
   When one query is screened against 7,000 targets, the query MSA (~20 min)
   is computed 7,000 times, with an identical result each time.
2. **Each GPU job has a fixed overhead.** Container start, model loading
   and featurisation add ~35–80 s to every pair, on top of 1–3.5 min of
   inference.
3. **MSA jobs use only ~22% of the CPUs they are given.** The database
   searches cannot keep all the cores busy.

## What the fast workflow does differently

| | standard workflow | fast workflow |
|---|---|---|
| MSAs | 1 job per **pair** (both chains, 18 cores) | 1 run per **unique protein**; 8 run side by side on a full CPU node |
| pair inputs | written by the MSA job | assembled from the per-protein MSAs ([02_assemble_pairs.py](02_assemble_pairs.py)) |
| prediction | 1 GPU job per pair | 1 GPU job per batch of e.g. 100 pairs |
| diffusion samples | 5 | 1 (configurable; use 5 when rerunning hits) |

**1. MSAs once per protein.** For *n* unique proteins in *m* pairs, the
data pipeline runs *n* times instead of *m* times. Each pair's input is then
built by copying `unpairedMsa`, `pairedMsa` and `templates` of each chain from
the per-protein `_data.json`. AF3 pairs the MSAs across chains itself when
it featurises the complex. This is the approach the AF3 developers recommend
([docs/performance.md, "Pre-computing and reusing MSA and templates"](https://github.com/google-deepmind/alphafold3/blob/main/docs/performance.md)).
In the benchmark, the assembled inputs were **identical** to the per-pair
inputs of the standard workflow for all 10 pairs (sequence, unpaired MSA,
paired MSA and templates of every chain, compared by checksum).

**2. 8 MSA processes per CPU node.** A full node (72 cores) runs 8 AF3
processes side by side. Each process is ~17% slower than one running alone,
but twice as many run at once as with 4. As a result, each protein costs 1.6x
fewer core-hours, with identical MSAs.

**3. Many pairs per GPU job, 1 sample per pair.** One AF3 run predicts a
whole batch (`--input_dir`), so the start-up cost is paid once per batch.
`--num_diffusion_samples 1` needs AF3 **3.0.1**. Both steps of the fast
workflow (MSA and prediction) run on 3.0.1. 3.0.1 uses the same model
weights as 3.0.0. In the benchmark the MSAs were still computed with 3.0.0
(see Benchmark).

## Benchmark

**Setup**
- 10 pairs from an earlier screen of one query protein against a proteome.
  The 10 targets cover the length range of that screen, from 170 to 1,140
  residues.
- One of the 10 pairs is a high-confidence hit (TARGET_09).
- **Standard:** the original runs of these 10 pairs.
- **Fast:** 1 CPU-node MSA job (4 workers, AF3 3.0.0), then 1 GPU job
  (AF3 3.0.1).
- **What was compared:** running time only, not queue time.
- **How core-h are counted:** running time × CPUs allocated, as SLURM counts
  them. Hyperthreads are included, so a full Raven node counts as 144.

**Totals, 10 pairs**

| | standard | fast | standard / fast |
|---|---:|---:|---:|
| SLURM jobs | 20 | 2 | 10x |
| MSA, allocated core-h | 212 | 132 | 1.6x |
| MSA, CPU-h actually used | 45.8 | 30.6 | 1.5x |
| GPU-h | 0.42 | 0.25 | 1.7x |

**Per pair.** The standard workflow used 5 samples and reports the
best-ranked one; the fast workflow used 1 sample.

| pair | target length [aa] | standard MSA job [min] | fast MSA, target only [min] | standard GPU job [min] | inference standard / fast [s] | ipTM standard / fast | ipTM range of the 5 standard samples |
|---|---:|---:|---:|---:|---:|---|---|
| QUERY–TARGET_01 | ~170 | 33.3 | 18.2 | 1.6 | 61 / 13 | 0.28 / 0.29 | 0.19–0.28 |
| QUERY–TARGET_02 | ~250 | 35.2 | 18.7 | 1.8 | 61 / 13 | 0.17 / 0.16 | 0.12–0.17 |
| QUERY–TARGET_03 | ~280 | 35.1 | 17.2 | 1.7 | 63 / 48* | 0.22 / 0.18 | 0.19–0.22 |
| QUERY–TARGET_04 | ~350 | 33.4 | 17.5 | 2.1 | 83 / 28 | 0.33 / 0.34 | 0.32–0.33 |
| QUERY–TARGET_05 | ~430 | 34.0 | 16.7 | 2.2 | 85 / 64* | 0.20 / 0.20 | 0.11–0.20 |
| QUERY–TARGET_06 | ~500 | 34.7 | 18.6 | 2.2 | 83 / 28 | 0.31 / 0.22 | 0.23–0.31 |
| QUERY–TARGET_07 | ~560 | 36.7 | 19.1 | 2.8 | 110 / 49 | 0.12 / 0.11 | 0.10–0.12 |
| QUERY–TARGET_08 | ~660 | 37.4 | 18.2 | 2.7 | 111 / 84* | 0.17 / 0.16 | 0.13–0.17 |
| **QUERY–TARGET_09 (hit)** | ~870 | 35.5 | 17.8 | 3.4 | 152 / 120* | **0.81 / 0.80** | 0.79–0.81 |
| QUERY–TARGET_10 | ~1140 | 38.7 | 18.6 | 4.7 | 203 / 163* | 0.18 / 0.14 | 0.16–0.18 |

- **MSA times.** The standard MSA job computes both chains one after the
  other: the query (~19 min) plus the target. In the fast workflow, the
  query MSA was computed **once** (22.8 min) for all 10 pairs.
- **MSA time hardly depends on length.** It was 17–19 min for targets of
  170 to 1,140 aa, because it is dominated by searching the databases. So
  [01_make_monomer_inputs.py](01_make_monomer_inputs.py) balances the
  workers by number of proteins, not by length.
- **\* JAX compilation.** These fast-workflow inference times include a
  one-off compilation, because each was the first pair of its size bucket in
  the job. Batches are therefore sorted by size, and
  `--jax_compilation_cache_dir` keeps compiled models between jobs.

**4 vs 8 MSA workers per node.** The same 11 proteins were run with
4 workers and with 8 workers, plus 5 extra proteins so that the 8 workers
were fully loaded.

| | 4 workers | 8 workers |
|---|---:|---:|
| time per protein (same 11 proteins), mean | 18.5 min | 21.6 min (+17%) |
| core-h per protein, node kept full | 11.1 | **6.8** |
| CPU usage of the node | 23% | 35% |
| memory used | – | 19 of 240 GB |
| MSAs | | identical to 4 workers |

**Extrapolated to the full screen (~7,400 pairs, 1 query vs. a proteome)**

| | standard | fast, 4 workers | fast, 8 workers |
|---|---:|---:|---:|
| MSA, allocated core-h | 157,554 | 82,253 | **50,653** (3.1x less) |
| GPU-h | 310 | 183 | 183 |
| SLURM jobs | 14,830 | | ~106 with the defaults in `config.sh` (31 MSA + 75 GPU) |

**Rule of thumb for planning**
- **MSAs:** ~7 core-h per unique protein.
- **Predictions:** ~1.5 GPU-min per pair for pairs up to ~1,500 residues
  with 1 sample.
- **Standard workflow, for comparison:** ~21 core-h and ~2.5 GPU-min per
  pair.

## How to run

### 0. Requirements
- An AF3 setup on Raven as in the [main README](../README.md), sections 1–3.
- Python 3. The scripts use only the standard library and run on the login
  node.

### 1. Configure
Edit [config.sh](config.sh). At minimum, set `SCREEN_DIR` and check
`AF3_USER_DIR`. Then put your pair list at `PAIRS_CSV`. It uses the same
format as [example_dataset.csv](../example_dataset.csv):
```csv
job_name,uid1,uid1_copies,uid2,uid2_copies
query_target01,QUERY_ID,1,TARGET_ID_01,1
query_target02,QUERY_ID,1,TARGET_ID_02,1
homodimer_target03,TARGET_ID_03,2,TARGET_ID_04,0
```
`uid1`/`uid2` are UniProt IDs. A copy number of 0 leaves that protein out,
so the last row is a homodimer of `TARGET_ID_03`.

### 2. Prepare the jobs (login node)
```bash
cd fast_screen
source config.sh
python3 01_make_monomer_inputs.py
```
This does four things:
- **Sequences:** it takes them from `UNIPROT_CACHE` or downloads them from
  UniProt. For sequences that are not in UniProt, add `uid,fasta` rows to
  the cache CSV yourself.
- **MSA inputs:** it writes one single-chain input per **unique** protein
  that is not yet in `MSA_LIBRARY`, split over CPU-node jobs and workers.
- **GPU batches:** it splits the pairs that are not yet predicted into
  batches.
- **Summary:** it prints how many MSA jobs and GPU jobs will be submitted.
  Check these numbers before you submit.

### 3. Submit
```bash
bash submit_fast_screen.sh
```
This submits one CPU-node job per MSA node folder
([jobscript_msa_node.sh](jobscript_msa_node.sh)) and one GPU job per batch
([jobscript_inference_batch.sh](jobscript_inference_batch.sh)). The GPU jobs
start when **all** MSA jobs have ended. Each GPU job first assembles its pair
inputs from the MSA library, then predicts them. Job IDs go to
`SCREEN_DIR/jobids.tsv`, and the logs go to `SCREEN_DIR/logs/`.

You do not need to leave a script running in the background as with
`msa_af3.sh`/`model_af3.sh`. SLURM handles the order of the jobs.

### 4. Check, resubmit, analyse
When all jobs have finished, run steps 2 and 3 again:
```bash
source config.sh && python3 01_make_monomer_inputs.py && bash submit_fast_screen.sh
```
- **Resuming is safe.** Proteins that already have an MSA and pairs that
  already have a prediction are skipped. So this picks up whatever failed or
  hit the time limit, and does nothing once the screen is complete.
- **You can't submit twice by mistake.** Both scripts refuse to run while
  jobs of the screen are still queued or running.
- **Results** are in `SCREEN_DIR/predictions/<job_name>/`, in the same
  layout as in the standard workflow (`ranking_scores.csv`,
  `seed-3141592_sample-0/`, ...). Run
  [AF3_analysis.py](../AF3_analysis.py) with
  `AF3_DIR = SCREEN_DIR/predictions`.

### Output layout
```
SCREEN_DIR/
├── pairs.csv, uniprot_cache.csv
├── msa_inputs/node_000/worker_0/<protein>.json   single-chain inputs (step 2)
├── msa_library/<protein>/<protein>_data.json     MSAs + templates per protein (= MSA_LIBRARY)
├── batches/batch_0000.tsv                        pairs per GPU job, sorted by size
├── inference_inputs/batch_0000/                  temporary, deleted after each GPU job
├── predictions/<job_name>/                       AF3 results per pair
├── skipped_pairs.tsv                             pairs without a sequence (if any)
├── logs/                                         SLURM logs + one log per MSA worker
└── jobids.tsv
```

## Recommendations and caveats

- **Rerun the hits with full sampling.** One sample instead of five changed
  non-hit ipTMs by up to 0.09 (TARGET_06: 0.31 → 0.22). The hit was stable,
  but the benchmark has only 10 pairs and one hit, so use the 1-sample
  screen to **rank** pairs, then rerun the top pairs with `NUM_SAMPLES=5`,
  or with more seeds via `MODEL_SEEDS`. To do that:
  1. Make a new `SCREEN_DIR` with a CSV of the hits.
  2. Point `MSA_LIBRARY` at the screen's library, so no MSA is recomputed.
  3. Note that [AF3_analysis.py](../AF3_analysis.py) reads the
     `seed-3141592_sample-*` folders, so keep 3141592 among the seeds.
- **Reuse MSAs across screens.** The MSA library does not depend on the
  partner protein. A new query against the same proteome needs only **one**
  new MSA, if `MSA_LIBRARY` points at the earlier library. If UniProt has
  since changed a sequence, step 2 stops and tells you which one.
- **Time limits.**
  - **MSA jobs:** in the benchmark, one protein took 19–40 min with
    8 workers. `SEQS_PER_WORKER=30` gives ~11–20 h per node job, inside the
    24 h limit.
  - **GPU jobs:** time grows steeply with complex size. The last batches
    hold the largest pairs.
  - **If a job hits its limit:** finished proteins and pairs are kept. Rerun
    step 2 and resubmit, as in step 4.
- **Large complexes.** The 1/4-node GPU setup (A100 40 GB) was tested only
  up to ~1,350 residues per pair. For much larger pairs, run them as a
  separate screen with the 1/2-node block in
  [jobscript_inference_batch.sh](jobscript_inference_batch.sh) switched on.
- **Disk space.** AF3 writes a copy of each pair input, MSAs included, to
  `predictions/<job_name>/<job_name>_data.json`. That is tens of MB per pair
  and hundreds of GB for a proteome screen. The same data is in the MSA
  library, so once the screen is finished and checked you can free the
  space with:
  ```bash
  find "$SCREEN_DIR/predictions" -name '*_data.json' -delete
  ```
- **Homomers.** Copies of a protein are written as one entry with several
  chain IDs (`"id": ["A", "B"]`), as the AF3 input format allows. The
  benchmark pairs were all 1:1, so this format has not been compared
  directly against the standard workflow.
- **Not yet tested on Raven:** the generalised scripts in this folder.
  - **Tested locally:** the assembly was checked against the real benchmark
    MSAs, and gives inputs identical to the original runs. Setup, batching,
    resubmission and the job-submission logic were tested on simulated
    data.
  - **Not yet tested:**
    - the MSA step on AF3 3.0.1 (the benchmark MSAs were made with 3.0.0);
    - several CPU nodes searching the shared AF3 databases at the same time;
    - more than 2 proteins per worker.
  - **First real run:** start with a small subset, e.g. 20–50 pairs.
- **Alternative from the AF3 docs.** You can also give the MSAs only for
  the fixed chain (e.g. the query) and leave them out for the other chain.
  AF3 then computes the missing MSA within the pair job. This needs no
  assembly step, but it keeps one job per pair and gives up the batching
  savings.

## Files

| file | what it does |
|---|---|
| [config.sh](config.sh) | all settings (paths, workers, batch size, samples, seeds) |
| [01_make_monomer_inputs.py](01_make_monomer_inputs.py) | step 2: sequences, single-chain MSA inputs, GPU batches |
| [jobscript_msa_node.sh](jobscript_msa_node.sh) | CPU-node MSA job (AF3 3.0.1, `--norun_inference`) |
| [02_assemble_pairs.py](02_assemble_pairs.py) | builds the pair inputs of one batch from the MSA library (run inside the GPU job) |
| [jobscript_inference_batch.sh](jobscript_inference_batch.sh) | GPU job for one batch (AF3 3.0.1, `--norun_data_pipeline`) |
| [submit_fast_screen.sh](submit_fast_screen.sh) | submits all MSA and GPU jobs with the right dependencies |
| [screen_utils.py](screen_utils.py) | helpers shared by the Python scripts |
