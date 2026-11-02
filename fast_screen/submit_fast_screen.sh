#!/bin/bash
# Fast AF3 screen: submit all jobs prepared by 01_make_monomer_inputs.py.
#   - one CPU-node MSA job per SCREEN_DIR/msa_inputs/node_<n>/
#   - one GPU job per SCREEN_DIR/batches/batch_<b>.tsv, each starting after
#     ALL MSA jobs have ended (afterany: if an MSA job fails, the GPU jobs
#     still predict every pair whose MSAs exist)
# Job IDs are appended to SCREEN_DIR/jobids.tsv.
#
# Usage (from anywhere):  bash submit_fast_screen.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1  # jobscripts find config.sh via $SLURM_SUBMIT_DIR
source config.sh

JOBIDS=${SCREEN_DIR}/jobids.tsv
[ -d "${SCREEN_DIR}/batches" ] || { echo "run 01_make_monomer_inputs.py first"; exit 1; }

# do not submit twice: two jobs predicting the same pair would clash
if [ -s "$JOBIDS" ]; then
    active=$(comm -12 <(tail -n +2 "$JOBIDS" | cut -f4 | sort) <(squeue -h -u "$USER" -o %i | sort))
    if [ -n "$active" ]; then
        echo "Jobs of this screen are still queued/running: $(echo $active)"
        echo "Wait for them or scancel them first."
        exit 1
    fi
fi
[ -s "$JOBIDS" ] || echo -e "submitted\tstage\tname\tjobid" > "$JOBIDS"
mkdir -p "${SCREEN_DIR}/logs"
now=$(date +%F_%T)

msa_ids=()
for node in "${SCREEN_DIR}"/msa_inputs/node_*/; do
    [ -d "$node" ] || continue
    name=$(basename "$node")
    id=$(sbatch --parsable -o "${SCREEN_DIR}/logs/slurm-%j.out" jobscript_msa_node.sh "$name") || exit 1
    msa_ids+=("$id")
    echo -e "${now}\tmsa\t${name}\t${id}" >> "$JOBIDS"
done

dep=()
if [ ${#msa_ids[@]} -gt 0 ]; then
    dep=(--dependency=afterany:$(IFS=:; echo "${msa_ids[*]}"))
fi

n_inf=0
for batch in "${SCREEN_DIR}"/batches/batch_*.tsv; do
    [ -f "$batch" ] || continue
    name=$(basename "$batch" .tsv)
    id=$(sbatch --parsable "${dep[@]}" -o "${SCREEN_DIR}/logs/slurm-%j.out" \
         jobscript_inference_batch.sh "$name") || exit 1
    echo -e "${now}\tinference\t${name}\t${id}" >> "$JOBIDS"
    n_inf=$((n_inf + 1))
done

echo "submitted ${#msa_ids[@]} MSA job(s) and ${n_inf} GPU job(s); job IDs in ${JOBIDS}"
