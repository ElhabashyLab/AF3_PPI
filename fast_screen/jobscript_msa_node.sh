#!/bin/bash -l
#SBATCH --job-name=AF3_fast_msa
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=240000
#SBATCH --time=24:00:00
#
# Fast AF3 screen, step 2 (CPU only): one full CPU node runs the AF3 data
# pipeline (MSAs + templates, no prediction) for the single-chain inputs in
# SCREEN_DIR/msa_inputs/<node>/. One run_alphafold.py process per worker_<k>/
# folder; the workers run side by side, the proteins of one worker one after
# the other. Results go to MSA_LIBRARY/<protein>/<protein>_data.json.
#
# Submitted by submit_fast_screen.sh as:  sbatch jobscript_msa_node.sh node_000

NODE=${1:?usage: sbatch jobscript_msa_node.sh <node folder, e.g. node_000>}

module purge
module load apptainer/1.3.2
module load alphafold/3.0.1

source "${SLURM_SUBMIT_DIR}/config.sh"
IN=${SCREEN_DIR}/msa_inputs/${NODE}
LOGS=${SCREEN_DIR}/logs
mkdir -p "$MSA_LIBRARY" "$LOGS"

for wdir in "$IN"/worker_*/; do
    w=$(basename "$wdir")
    export TMPDIR=/ptmp/${USER}/tmp/${SLURM_JOBID}/${w}
    mkdir -p "$TMPDIR"
    (
        echo "[$(date)] ${NODE}/${w} start"
        apptainer --quiet exec --bind /u:/u,/ptmp:/ptmp,/raven:/raven \
            ${AF3_IMAGE_SIF} \
            python3 /app/alphafold/run_alphafold.py \
            --db_dir $AF3_DB_DIR \
            --model_dir $AF3_MODEL_DIR \
            --input_dir "$wdir" \
            --output_dir "$MSA_LIBRARY" \
            --norun_inference
        echo "[$(date)] ${NODE}/${w} end (exit $?)"
    ) > "${LOGS}/msa_${SLURM_JOBID}_${NODE}_${w}.log" 2>&1 &
done
wait
rm -rf /ptmp/${USER}/tmp/${SLURM_JOBID}

# Fail the job if any protein of this node has no MSA. The GPU jobs still run
# (they depend on this job with afterany) and leave out the affected pairs.
missing=0
for json in "$IN"/worker_*/*.json; do
    name=$(basename "$json" .json)
    if [ ! -s "${MSA_LIBRARY}/${name}/${name}_data.json" ]; then
        echo "no MSA for ${name}"
        missing=$((missing + 1))
    fi
done
echo "${NODE}: ${missing} protein(s) without MSA"
[ "$missing" -eq 0 ]
