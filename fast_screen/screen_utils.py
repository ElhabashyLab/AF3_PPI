"""Helpers shared by 01_make_monomer_inputs.py and 02_assemble_pairs.py."""
import csv
import json
import os
import re
import subprocess
import sys

ALLOWED_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-.")


def af3_name(name):
    """The folder name AF3 writes the outputs of an input called `name` to
    (same rule as AF3's Input.sanitised_name)."""
    return "".join(c for c in name.lower().replace(" ", "_") if c in ALLOWED_NAME_CHARS)


def env(key):
    value = os.environ.get(key)
    if not value:
        sys.exit("{} is not set - run 'source config.sh' first.".format(key))
    return value


def screen_paths():
    screen = env("SCREEN_DIR")
    return {
        "screen": screen,
        "library": env("MSA_LIBRARY"),
        "msa_inputs": os.path.join(screen, "msa_inputs"),
        "batches": os.path.join(screen, "batches"),
        "inference_inputs": os.path.join(screen, "inference_inputs"),
        "predictions": os.path.join(screen, "predictions"),
        "jobids": os.path.join(screen, "jobids.tsv"),
    }


def library_data_json(library, chain):
    return os.path.join(library, chain, chain + "_data.json")


def prediction_done(predictions, job_name):
    name = af3_name(job_name)
    return os.path.exists(os.path.join(predictions, name, name + "_summary_confidences.json"))


def library_sequence(path):
    """Sequence stored in an MSA library _data.json. AF3 writes "sequence"
    near the top of the file, so only the start is read (the MSAs make the
    file tens of MB)."""
    with open(path) as f:
        head = f.read(1 << 20)
    m = re.search(r'"sequence"\s*:\s*"([A-Za-z]+)"', head)
    if m:
        return m.group(1)
    with open(path) as f:
        return json.load(f)["sequences"][0]["protein"]["sequence"]


def model_seeds():
    return [int(s) for s in env("MODEL_SEEDS").split(",") if s.strip()]


def active_jobs(jobids_path):
    """Job IDs from jobids.tsv that are still queued or running."""
    if not os.path.exists(jobids_path):
        return []
    with open(jobids_path) as f:
        ids = {r["jobid"] for r in csv.DictReader(f, delimiter="\t")}
    try:
        out = subprocess.run(["squeue", "-h", "-u", os.environ.get("USER", ""), "-o", "%i"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        print("WARNING: could not run squeue - not checking for running jobs.")
        return []
    return sorted(ids & set(out.split()))
