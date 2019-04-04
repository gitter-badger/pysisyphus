#!/usr/bin/env python3

import argparse
import copy
import itertools as it
import os
from pathlib import Path
from pprint import pprint
import re
import sys

from natsort import natsorted
import numpy as np
import rmsd as rmsd
import yaml

from pysisyphus.constants import BOHR2ANG
from pysisyphus.cos import *
from pysisyphus.Geometry import Geometry
from pysisyphus.helpers import (geom_from_xyz_file, geoms_from_trj, procrustes,
                                get_coords_diffs)
from pysisyphus.xyzloader import write_geoms_to_trj
from pysisyphus.stocastic.align import match_geom_atoms
from pysisyphus.interpolate import *


INTERPOLATE = {
    "idpp": IDPP.IDPP,
    "lst": LST.LST,
    "linear": Interpolator.Interpolator,
}


def parse_args(args):
    parser = argparse.ArgumentParser("Utility to transform .xyz and .trj files.")

    parser.add_argument("fns", nargs="+",
            help="Filenames of .xyz and/or .trj files (xyz and trj can be mixed)."
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--between", type=int, default=0,
                    help="Interpolate additional images."
    )
    action_group.add_argument("--align", action="store_true",
                    help="Align geometries onto the first geometry."
    )
    action_group.add_argument("--split", action="store_true",
                    help="Split a supplied geometries in multiple .xyz files."
    )
    action_group.add_argument("--reverse", action="store_true",
                    help="Reverse a .trj file."
    )
    action_group.add_argument("--cleantrj", action="store_true",
                    help="Keep only the first four columns of xyz/trj files."
    )
    action_group.add_argument("--spline", action="store_true",
                    help="Evenly redistribute geometries along a splined path."
    )
    action_group.add_argument("--first", type=int,
                    help="Copy the first N geometries to a new .trj file."
    )
    action_group.add_argument("--every", type=int,
                    help="Create new .trj with every N-th geometry. "
                         "Always includes the first and last point."
    )
    action_group.add_argument("--center", action="store_true",
                    help="Move the molecules centroid into the origin."
    )
    action_group.add_argument("--translate", nargs=3, type=float,
                    help="Translate the molecule by the given vector given " \
                         "in Ångström."
    )
    action_group.add_argument("--append", action="store_true",
                    help="Combine the given .xyz files into one .xyz file."
    )
    action_group.add_argument("--join", action="store_true",
                    help="Combine the given .xyz/.trj files into one .trj file."
    )
    action_group.add_argument("--match", action="store_true",
            help="Resort the second .xyz file so the atom order matches the "
                 "first .xyz file. Uses the hungarian method."
    )

    interpolate_group = parser.add_mutually_exclusive_group()
    interpolate_group.add_argument("--idpp", action="store_true",
        help="Interpolate using Image Dependent Pair Potential."
    )
    interpolate_group.add_argument("--lst", action="store_true",
        help="Interpolate by linear synchronous transit."
    )
    parser.add_argument("--bohr", action="store_true",
                    help="Input geometries are in Bohr instead of Angstrom."
    )
    parser.add_argument("--noxyz", action="store_false",
                    help="Disable dumping of single .xyz files."
    )

    return parser.parse_args()


def read_geoms(xyz_fns, in_bohr=False, coord_type="cart"):
    if isinstance(xyz_fns, str):
        xyz_fns = [xyz_fns, ]

    geoms = list()
    for fn in xyz_fns:
        if "*" in fn:
            cwd = Path(".")
            geom = [geom_from_xyz_file(xyz_fn)
                    for xyz_fn in natsorted(cwd.glob(fn))]
        elif fn.endswith(".xyz"):
            geom = [geom_from_xyz_file(fn, coord_type=coord_type), ]
        elif fn.endswith(".trj"):
            geom = geoms_from_trj(fn, coord_type=coord_type)
        else:
            raise Exception("Only .xyz and .trj files are supported!")
        geoms.extend(geom)
    # Original coordinates are in bohr, but pysisyphus expects them
    # to be in Angstrom, so right now they are already multiplied
    # by ANG2BOHR. We revert this by multip
    if in_bohr:
        for geom in geoms:
            geom.coords *= BOHR2ANG
    return geoms


def get_geoms(xyz_fns, interpolate=None, between=0,
              coord_type="cart", comments=False, in_bohr=False):
    """Returns a list of Geometry objects in the given coordinate system
    and interpolates if necessary."""

    assert interpolate in list(INTERPOLATE.keys()) + [None]

    geoms = read_geoms(xyz_fns, in_bohr, coord_type=coord_type)

    print(f"Read {len(geoms)} geometries.")

    if interpolate:
        interpolate_class = INTERPOLATE[interpolate]
        interpolator = interpolate_class(geoms, between)
        geoms = interpolator.interpolate_all()

    return geoms


def dump_geoms(geoms, fn_base, trj_infix="", dump_trj=True, dump_xyz=True,
               ang=False):
    xyz_per_geom = [geom.as_xyz() for geom in geoms]
    if dump_trj:
        trj_str = "\n".join(xyz_per_geom)
        trj_fn = f"{fn_base}{trj_infix}.trj"
        with open(trj_fn, "w") as handle:
            handle.write(trj_str)
        print(f"Wrote all geometries to {trj_fn}.")
    if dump_xyz:
        for i, xyz in enumerate(xyz_per_geom):
            geom_fn = f"{fn_base}.geom_{i:03d}.xyz"
            with open(geom_fn, "w") as handle:
                handle.write(xyz)
            print(f"Wrote geom {i:03d} to {geom_fn}.")
    print()


def align(geoms):
    """Align all geometries onto the first using partical procrustes."""
    cos = ChainOfStates.ChainOfStates(geoms)
    procrustes(cos)
    return [geom for geom in cos.images]


def spline_redistribute(geoms):
    szts = SimpleZTS.SimpleZTS(geoms)
    pre_diffs = get_coords_diffs([image.coords for image in szts.images])
    szts.reparametrize()
    post_diffs = get_coords_diffs(szts.coords.reshape(-1,3))
    post_diffs = get_coords_diffs([image.coords for image in szts.images])
    cds_str = lambda cds: " ".join([f"{cd:.2f}" for cd in cds])
    print("Normalized path segments before splining:")
    print(cds_str(pre_diffs))
    print("Normalized path segments after redistribution along spline:")
    print(cds_str(post_diffs))
    return szts.images


def every(geoms, every_nth):
    # every_nth_geom = geoms[::every_nth]
    # The first geometry is always present, but the last geometry
    # may be missing.
    sampled_indices = list(range(0, len(geoms), every_nth))
    if sampled_indices[-1] != len(geoms)-1:
        sampled_indices.append(len(geoms)-1)
    sampled_inds_str = ", ".join([str(i) for i in sampled_indices])
    print(f"Sampled indices {sampled_inds_str}")
    # if every_nth_geom[-1] != geoms[-1]:
        # every_nth_geom.append(geoms[-1])
    every_nth_geom = [geoms[i] for i in sampled_indices]
    return every_nth_geom


def center(geoms):
    for geom in geoms:
        geom.coords3d = geom.coords3d - geom.centroid
    return geoms


def translate(geoms, trans):
    for geom in geoms:
        geom.coords3d += trans
    return geoms


def append(geoms):
    atoms = geoms[0].atoms * len(geoms)
    coords = list(it.chain([geom.coords for geom in geoms]))
    return [Geometry(atoms, coords), ]


def bohr2ang(geoms):
    coords_angstrom = [geom.coords*0.529177249 for geom in geoms]
    import pdb; pdb.set_trace()
    raise Exception("Implement me")


def match(ref_geom, geom_to_match):
    rmsd_before = rmsd.kabsch_rmsd(ref_geom.coords3d, geom_to_match.coords3d)
    print(f"Kabsch RMSD before: {rmsd_before:.4f}")
    matched_geom = match_geom_atoms(ref_geom, geom_to_match, hydrogen=True)

    # Right now the atoms are not in the right order as we only sorted the
    # individual coord blocks by atom.
    # This dictionary will hold the counter indices for the individual atom
    atom_type_inds = {atom: 0 for atom in ref_geom.atom_types}
    matched_coord_blocks, _ = matched_geom.coords_by_type
    new_coords = list()
    for atom in ref_geom.atoms:
        # Get the current counter/index from the dicitonary for the given atom
        cur_atom_ind = atom_type_inds[atom]
        # Select the appropriate atom from the coords block
        atom_coords = matched_coord_blocks[atom][cur_atom_ind]
        new_coords.append(atom_coords)
        # Increment the counter so the next time the same atom type comes up
        # we fetch the next entry of the coord block.
        atom_type_inds[atom] += 1
    # Assign the updated atom order and corresponding coordinates
    matched_geom.atoms = ref_geom.atoms
    matched_geom.coords = np.array(new_coords).flatten()
    rmsd_after = rmsd.kabsch_rmsd(ref_geom.coords3d, matched_geom.coords3d)
    print(f"Kabsch RMSD after: {rmsd_after:.4f}")
    return [matched_geom, ]


def run():
    args = parse_args(sys.argv[1:])

    if args.idpp:
        interpolate = INTERPOLATE["idpp"]
    elif args.lst:
        interpolate = INTERPOLATE["lst"]
    elif args.between:
        interpolate = INTERPOLATE["linear"]
    else:
        interpolate = None

    # Read supplied files and create Geometry objects
    geoms = get_geoms(args.fns, interpolate, args.between, in_bohr=args.bohr)

    to_dump = geoms
    dump_trj = True
    dump_xyz = args.noxyz
    trj_infix = ""
    if args.between:
        fn_base = "interpolated"
    elif args.align:
        to_dump = align(geoms)
        fn_base = "aligned"
    elif args.split:
        fn_base = "split"
        dump_trj = False
    elif args.reverse:
        to_dump = geoms[::-1]
        fn_base = "reversed"
    elif args.cleantrj:
        fn_base = "cleaned"
    elif args.first:
        to_dump = geoms[:args.first]
        fn_base = "first"
        trj_infix = f"_{args.first}"
    elif args.spline:
        to_dump = spline_redistribute(geoms)
        fn_base = "splined"
    elif args.every:
        to_dump = every(geoms, args.every)
        fn_base = "every"
        trj_infix = f"_{args.every}th"
    elif args.center:
        to_dump = center(geoms)
        fn_base = "centered"
    elif args.translate:
        trans = np.array(args.translate) / BOHR2ANG
        to_dump = translate(geoms, trans)
        fn_base = "translated"
    elif args.append:
        to_dump = append(geoms)
        fn_base = "appended"
    elif args.join:
        to_dump = geoms
        fn_base = "joined"
    elif args.match:
        to_dump = match(*geoms)
        fn_base = "matched"

    # Write transformed geometries
    dump_trj = dump_trj and (len(to_dump) > 1)

    dump_geoms(to_dump, fn_base, trj_infix=trj_infix, dump_trj=dump_trj,
               dump_xyz=dump_xyz)

if __name__ == "__main__":
    run()
