# Settings for the fast AF3 screen. Edit this file before you start.
# All scripts in fast_screen/ read it:
#   source config.sh && python3 01_make_monomer_inputs.py
#   bash submit_fast_screen.sh

# ---- where things are -------------------------------------------------------
# Everything the screen writes goes into SCREEN_DIR.
export SCREEN_DIR=/ptmp/${USER}/my_af3_screen
# Pair list, same format as example_dataset.csv:
# job_name,uid1,uid1_copies,uid2,uid2_copies
export PAIRS_CSV=${SCREEN_DIR}/pairs.csv
# UniProt sequence cache (uid,fasta), same format as AF3_json_1seed.py uses.
# IDs already in here are not downloaded again.
export UNIPROT_CACHE=${SCREEN_DIR}/uniprot_cache.csv
# Per-protein MSAs + templates (<name>/<name>_data.json). Point this at the
# library of an earlier screen to reuse its MSAs: only new proteins are run.
export MSA_LIBRARY=${SCREEN_DIR}/msa_library

# Your AF3 model parameters and JAX cache (same as in mpcdf/parameters.inc).
export AF3_USER_DIR=${HOME}/alphafold_3_0_0
export AF3_MODEL_DIR=${AF3_USER_DIR}/model
export AF3_JAX_CACHE_DIR=${AF3_USER_DIR}/jaxcache

# ---- MSA step (CPU nodes) ---------------------------------------------------
# AF3 processes running side by side on one CPU node. 8 was tested to be
# 1.6x cheaper per protein than 4, with identical MSAs.
export N_WORKERS=8
# Proteins per worker, i.e. one node job runs N_WORKERS x SEQS_PER_WORKER
# proteins. One protein took ~20-40 min with 8 workers, so 30 per worker
# is ~11-20 h, inside Raven's 24 h limit.
export SEQS_PER_WORKER=30

# ---- prediction step (GPU) --------------------------------------------------
# Pairs predicted in one GPU job. Pairs are sorted by size, so the last
# batches hold the largest complexes and take longest.
export BATCH_SIZE=100
# Diffusion samples per seed. 1 for screening, 5 (AF3 default) to rerun hits.
export NUM_SAMPLES=1
# Comma-separated model seeds (AF3_analysis.py expects 3141592).
export MODEL_SEEDS=3141592
