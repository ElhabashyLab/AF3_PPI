#!/bin/bash -l
#SBATCH --job-name=AF3_fast_inf
#SBATCH --ntasks=1
#SBATCH --constraint=gpu
#SBATCH --time=12:00:00

# 1/4 node (as mpcdf/jobscript-alphafold3-step_2-prediction.sh)
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=18
#SBATCH --mem=125000

# 1/2 node, for large complexes (comment '##' the block above, uncomment
# this one and set XLA_CLIENT_MEM_FRACTION below to 6.0):
##SBATCH --gres=gpu:a100:2
##SBATCH --cpus-per-task=36
##SBATCH --mem=250000
#
# Fast AF3 screen, step 3 (GPU): assemble the pair inputs of one batch from
# the MSA library (02_assemble_pairs.py), then predict ALL of them in ONE
# AF3 run. Container start, model loading and JAX compilation happen once
# per job instead of once per pair.
# Runs on AF3 3.0.1 (same version as the MSA step) for its
# --num_diffusion_samples flag (NUM_SAMPLES in config.sh).
#
# Submitted by submit_fast_screen.sh as:  sbatch jobscript_inference_batch.sh batch_0000
# A batch that hit the time limit can be resubmitted as is: finished pairs
# are skipped.

BATCH=${1:?usage: sbatch jobscript_inference_batch.sh <batch, e.g. batch_0000>}

module purge
module load apptainer/1.3.2
module load alphafold/3.0.1

source "${SLURM_SUBMIT_DIR}/config.sh"
INF_IN=${SCREEN_DIR}/inference_inputs/${BATCH}
mkdir -p "$AF3_JAX_CACHE_DIR" "${SCREEN_DIR}/predictions"

python3 "${SLURM_SUBMIT_DIR}/02_assemble_pairs.py" "$BATCH" || exit 1
n=$(find "$INF_IN" -name '*.json' | wc -l)
if [ "$n" -eq 0 ]; then
    echo "${BATCH}: nothing to predict"
    rm -rf "$INF_IN"
    exit 0
fi

export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export TMPDIR=${JOB_TMPDIR}
export XLA_FLAGS="--xla_gpu_enable_triton_gemm=false"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export TF_FORCE_UNIFIED_MEMORY=true
export XLA_CLIENT_MEM_FRACTION="3.0"

srun apptainer --quiet exec --bind /u:/u,/ptmp:/ptmp,/raven:/raven --nv \
    ${AF3_IMAGE_SIF} \
    python3 /app/alphafold/run_alphafold.py \
    --db_dir $AF3_DB_DIR \
    --model_dir $AF3_MODEL_DIR \
    --input_dir "$INF_IN" \
    --output_dir "${SCREEN_DIR}/predictions" \
    --jax_compilation_cache_dir $AF3_JAX_CACHE_DIR \
    --num_diffusion_samples $NUM_SAMPLES \
    --norun_data_pipeline
status=$?

# AF3 keeps a copy of every input as predictions/<pair>/<pair>_data.json
rm -rf "$INF_IN"
exit $status
