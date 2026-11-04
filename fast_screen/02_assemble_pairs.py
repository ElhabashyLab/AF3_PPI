#!/usr/bin/env python3
"""
Fast AF3 screen, step 3 (run by jobscript_inference_batch.sh at the start of
each GPU job): build the pair inputs of one batch from the MSA library.

Each chain gets the unpairedMsa, pairedMsa and templates of its protein
exactly as the single-chain MSA run wrote them. AF3 pairs the MSAs of the
chains itself when it featurises the complex, so the pair input is the same
as what a per-pair MSA run would have produced (checked byte by byte in the
benchmark, see README.md). Copies of a protein share one entry with several
chain IDs, e.g. "id": ["A", "B"].

Pairs that already have a prediction are left out, so a batch that hit the
time limit can simply be resubmitted. A prediction folder without
<name>_summary_confidences.json is an interrupted run and is deleted first:
otherwise AF3 would write the new result to <name>_<timestamp>/ instead.
Pairs with a missing MSA are reported and left out.

Writes SCREEN_DIR/inference_inputs/<batch>/<job_name>.json

Usage:  python3 02_assemble_pairs.py batch_0000   (with config.sh sourced)
"""
import collections
import csv
import json
import os
import shutil
import sys

from screen_utils import af3_name, library_data_json, model_seeds, prediction_done, screen_paths


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    batch = sys.argv[1]
    p = screen_paths()
    seeds = model_seeds()
    with open(os.path.join(p["batches"], batch + ".tsv")) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    def chains(row):
        return [(row[c], int(row[n])) for c, n in (("chain1", "copies1"), ("chain2", "copies2")) if int(row[n]) > 0]

    out_dir = os.path.join(p["inference_inputs"], batch)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)

    # proteins used by several pairs of this batch (e.g. a common query) are
    # read once; the others are not kept in memory
    uses = collections.Counter(c for row in rows for c, _ in chains(row))
    cache = {}

    def load(chain):
        if chain in cache:
            return cache[chain]
        with open(library_data_json(p["library"], chain)) as f:
            protein = json.load(f)["sequences"][0]["protein"]
        if uses[chain] > 1:
            cache[chain] = protein
        return protein

    written, done, no_msa = 0, 0, []
    for row in rows:
        job = row["job_name"]
        if prediction_done(p["predictions"], job):
            done += 1
            continue
        pred_dir = os.path.join(p["predictions"], af3_name(job))
        if os.path.isdir(pred_dir):
            print("removing interrupted prediction {}".format(pred_dir))
            shutil.rmtree(pred_dir)
        missing = [c for c, _ in chains(row) if not os.path.exists(library_data_json(p["library"], c))]
        if missing:
            no_msa.append((job, missing))
            continue

        sequences, next_id = [], 0
        for chain, copies in chains(row):
            protein = dict(load(chain))  # shallow copy: only "id" is changed
            ids = [chr(ord("A") + next_id + i) for i in range(copies)]
            next_id += copies
            protein["id"] = ids if copies > 1 else ids[0]
            sequences.append({"protein": protein})
        pair = {"dialect": "alphafold3", "version": 1, "name": job,
                "modelSeeds": seeds, "sequences": sequences}
        with open(os.path.join(out_dir, af3_name(job) + ".json"), "w") as f:
            json.dump(pair, f)
        written += 1

    for job, missing in no_msa:
        print("NO MSA for {} ({}) - left out; rerun 01_make_monomer_inputs.py".format(job, ", ".join(missing)))
    print("{}: {} pair inputs written, {} already predicted, {} without MSA".format(
        batch, written, done, len(no_msa)))


if __name__ == "__main__":
    main()
