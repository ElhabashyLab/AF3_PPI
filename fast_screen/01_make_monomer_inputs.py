#!/usr/bin/env python3
"""
Fast AF3 screen, step 1 (run on the login node): prepare the MSA and GPU jobs.

AF3 computes the MSAs and templates of each chain on its own, independent of
the partner chain. So instead of one MSA job per pair, every UNIQUE protein
gets one single-chain MSA run, and the pairs are later assembled from these
results (02_assemble_pairs.py). For n proteins in m pairs that is n MSA runs
instead of m (each with 2 chains).

Reads the pair list (same CSV format as the rest of this repo:
job_name,uid1,uid1_copies,uid2,uid2_copies), takes the sequences from the
cache CSV or downloads them from UniProt, and writes to SCREEN_DIR:

  msa_inputs/node_<n>/worker_<k>/<protein>.json
      one single-chain AF3 input per protein that is not yet in MSA_LIBRARY.
      Each node_<n> folder is one CPU-node job (jobscript_msa_node.sh), each
      worker_<k> folder one AF3 process on that node.
  batches/batch_<b>.tsv
      the pairs that still need a prediction, sorted by size and split into
      GPU jobs of BATCH_SIZE pairs (jobscript_inference_batch.sh).
  skipped_pairs.tsv
      pairs left out because a sequence could not be found (if any).

Safe to rerun, e.g. after a job hit the time limit: proteins already in the
MSA library and pairs already predicted are left out, and msa_inputs/ and
batches/ are rewritten from scratch. Refuses to run while jobs of this screen
are still queued or running.

Usage:  source config.sh && python3 01_make_monomer_inputs.py
"""
import csv
import json
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

from screen_utils import (active_jobs, af3_name, env, library_data_json, library_sequence,
                          prediction_done, screen_paths)

STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
MAX_CHAINS = 26  # chain IDs A-Z


# ---------------------------------------------------------------- sequences
def read_cache(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {r["uid"]: r["fasta"] for r in csv.DictReader(f) if r.get("fasta")}


def write_cache(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uid", "fasta"])
        for uid in sorted(cache):
            w.writerow([uid, cache[uid]])
    os.replace(tmp, path)


def fetch_uniprot(uid, retries=3):
    """Sequence of a UniProt entry ('' if it cannot be found)."""
    url = "https://rest.uniprot.org/uniprotkb/{}.fasta".format(uid)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                lines = r.read().decode().splitlines()
            return "".join(lines[1:]).strip().upper()  # drop the FASTA header
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return ""
        except urllib.error.URLError:
            pass
        time.sleep(5 * (attempt + 1))
    return ""


# ---------------------------------------------------------------- pairs
def read_pairs(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    required = {"job_name", "uid1", "uid1_copies", "uid2", "uid2_copies"}
    if not rows or not required <= set(rows[0]):
        sys.exit("{} needs the columns {}".format(path, ",".join(sorted(required))))
    pairs, seen = [], {}
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        job = r["job_name"].strip()
        name = af3_name(job)
        if not name:
            sys.exit("line {}: empty job_name".format(i))
        if name in seen:
            sys.exit("line {}: job_name '{}' gives the same AF3 output folder '{}' as line {}"
                     .format(i, job, name, seen[name]))
        seen[name] = i
        chains = [(r["uid1"].strip(), int(r["uid1_copies"])), (r["uid2"].strip(), int(r["uid2_copies"]))]
        n_chains = sum(c for _, c in chains)
        if any(c < 0 for _, c in chains) or n_chains == 0:
            sys.exit("line {}: copy numbers must be >= 0 and not both 0".format(i))
        if n_chains > MAX_CHAINS:
            sys.exit("line {}: more than {} chains".format(i, MAX_CHAINS))
        pairs.append((job, [(uid, c) for uid, c in chains if c > 0]))
    return pairs


# ---------------------------------------------------------------- distribution
def snake(items, k):
    """Deal items into k lists in snake order (0..k-1, k-1..0, ...). With
    items sorted by size this gives each list a similar count and mix."""
    out = [[] for _ in range(k)]
    for i, item in enumerate(items):
        rnd, pos = divmod(i, k)
        out[pos if rnd % 2 == 0 else k - 1 - pos].append(item)
    return out


def monomer_json(name, seq):
    # The seed is required by the input format but unused: the MSA run
    # (--norun_inference) does not predict.
    return {"name": name, "modelSeeds": [1],
            "sequences": [{"protein": {"id": "A", "sequence": seq}}],
            "dialect": "alphafold3", "version": 1}


def main():
    p = screen_paths()
    pairs_csv, cache_csv = env("PAIRS_CSV"), env("UNIPROT_CACHE")
    n_workers, per_worker, batch_size = (int(env(k)) for k in ("N_WORKERS", "SEQS_PER_WORKER", "BATCH_SIZE"))

    running = active_jobs(p["jobids"])
    if running:
        sys.exit("Jobs of this screen are still queued/running ({}) - wait for them or scancel them first."
                 .format(", ".join(running)))

    pairs = read_pairs(pairs_csv)
    uids = sorted({uid for _, chains in pairs for uid, _ in chains})

    # ---- sequences: cache first, then UniProt
    cache = read_cache(cache_csv)
    to_fetch = [u for u in uids if u not in cache]
    if to_fetch:
        print("downloading {} sequences from UniProt ...".format(len(to_fetch)))
    failed = set()
    for i, uid in enumerate(to_fetch, 1):
        seq = fetch_uniprot(uid)
        if seq:
            cache[uid] = seq
        else:
            failed.add(uid)
            print("  could not get a sequence for {}".format(uid))
        if i % 100 == 0:
            write_cache(cache_csv, cache)
            print("  {}/{}".format(i, len(to_fetch)))
    if to_fetch:
        write_cache(cache_csv, cache)

    # ---- unique proteins -> library names
    chain_name, by_name = {}, {}
    for uid in uids:
        if uid in failed:
            continue
        name = af3_name(uid)
        if name in by_name:
            sys.exit("IDs '{}' and '{}' map to the same MSA name '{}'".format(by_name[name], uid, name))
        by_name[name] = uid
        chain_name[uid] = name
        odd = set(cache[uid]) - STANDARD_AA
        if odd:
            print("NOTE: {} contains non-standard residues {}".format(uid, "".join(sorted(odd))))

    # ---- which proteins still need an MSA
    todo, reused = [], 0
    for uid, name in chain_name.items():
        data = library_data_json(p["library"], name)
        if os.path.exists(data):
            if library_sequence(data) != cache[uid]:
                sys.exit("{} is in the MSA library with a different sequence than {} has now "
                         "(UniProt update?). Remove {} or use another MSA_LIBRARY."
                         .format(name, uid, os.path.dirname(data)))
            reused += 1
        elif os.path.isdir(os.path.dirname(data)) and os.listdir(os.path.dirname(data)):
            # AF3 would write to <name>_<timestamp>/ instead and the MSA
            # would not be found
            sys.exit("{} exists but has no {}_data.json (interrupted run?). Remove it and rerun."
                     .format(os.path.dirname(data), name))
        else:
            todo.append((name, cache[uid]))

    shutil.rmtree(p["msa_inputs"], ignore_errors=True)
    todo.sort(key=lambda t: -len(t[1]))
    n_nodes = math.ceil(len(todo) / (n_workers * per_worker))
    for n, node in enumerate(snake(todo, n_nodes) if n_nodes else []):
        for k, worker in enumerate(snake(node, min(n_workers, len(node)))):
            wdir = os.path.join(p["msa_inputs"], "node_{:03d}".format(n), "worker_{}".format(k))
            os.makedirs(wdir)
            for name, seq in worker:
                with open(os.path.join(wdir, name + ".json"), "w") as f:
                    json.dump(monomer_json(name, seq), f, indent=1)

    # ---- pairs that still need a prediction -> GPU batches
    skipped, done, open_pairs = [], 0, []
    for job, chains in pairs:
        missing = [uid for uid, _ in chains if uid in failed]
        if missing:
            skipped.append((job, ",".join(missing)))
        elif prediction_done(p["predictions"], job):
            done += 1
        else:
            n_res = sum(len(cache[uid]) * c for uid, c in chains)
            open_pairs.append((n_res, job, [(chain_name[uid], c) for uid, c in chains]))
    open_pairs.sort(key=lambda t: t[0])

    shutil.rmtree(p["batches"], ignore_errors=True)
    os.makedirs(p["batches"])
    n_batches = math.ceil(len(open_pairs) / batch_size)
    for b in range(n_batches):
        rows = open_pairs[b * batch_size:(b + 1) * batch_size]
        with open(os.path.join(p["batches"], "batch_{:04d}.tsv".format(b)), "w") as f:
            f.write("job_name\tchain1\tcopies1\tchain2\tcopies2\tn_residues\n")
            for n_res, job, chains in rows:
                (c1, n1), (c2, n2) = chains if len(chains) == 2 else chains + [("", 0)]
                f.write("{}\t{}\t{}\t{}\t{}\t{}\n".format(job, c1, n1, c2, n2, n_res))

    skipped_path = os.path.join(p["screen"], "skipped_pairs.tsv")
    if skipped:
        with open(skipped_path, "w") as f:
            f.write("job_name\tmissing_sequence\n")
            f.writelines("{}\t{}\n".format(*s) for s in skipped)
    elif os.path.exists(skipped_path):
        os.remove(skipped_path)

    # ---- summary
    print("\npairs:    {} in {}".format(len(pairs), pairs_csv))
    print("          {} already predicted, {} to predict, {} skipped (no sequence{})".format(
        done, len(open_pairs), len(skipped), " -> skipped_pairs.tsv" if skipped else ""))
    print("proteins: {} unique, {} already in the MSA library, {} need an MSA".format(
        len(chain_name), reused, len(todo)))
    print("MSA jobs: {} CPU node job(s), {} workers each, <= {} proteins per worker".format(
        n_nodes, n_workers, per_worker))
    if open_pairs:
        print("GPU jobs: {} batch(es) of <= {} pairs, {}-{} residues per pair".format(
            n_batches, batch_size, open_pairs[0][0], open_pairs[-1][0]))
    print("\nnext: bash submit_fast_screen.sh")


if __name__ == "__main__":
    main()
