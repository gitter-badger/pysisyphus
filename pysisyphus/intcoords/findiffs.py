#!/usr/bin/env python3

import itertools as it

import numpy as np

from pysisyphus.Geometry import Geometry
from pysisyphus.InternalCoordinates import RedundantCoords
from pysisyphus.intcoords.derivatives import d2q_b, d2q_a, d2q_d


np.set_printoptions(suppress=True, precision=6)


def prim_findiff(prim, coords3d, redund, delta=1e-4):
    """Derivatives of the primitive internal wrt the cartesian coordinates
    by finite differences."""

    inds = prim.inds
    # Indices for coords3d to generate the finite difference displacements.
    displacement_inds = [(i, j) for i, j in it.product(inds, (0, 1, 2))]

    funcs = {
        2: lambda coords: redund.calc_stretch(coords, inds),
        3: lambda coords: redund.calc_bend(coords, inds),
        4: lambda coords: redund.calc_dihedral(coords, inds),
    }
    func = funcs[len(inds)]

    grads = np.zeros_like(coords3d)
    for atom_ind, ax_ind in displacement_inds:
        # Calculate primitive internal value (bond length, bond angle,
        # dihedral) at slightly displaced geometry.
        plus = coords3d.copy()
        plus[atom_ind, ax_ind] += delta
        plus_val = func(plus)
        minus = coords3d.copy()
        minus[atom_ind, ax_ind] -= delta
        minus_val = func(minus)
        grads[atom_ind, ax_ind] = (plus_val - minus_val) / (2 * delta)
    return grads


def B_findiff(prim, coords3d, redund, delta=1e-4):
    """Derivatives of the Wilson B-Matrix by finite differences."""
    inds = prim.inds
    displacement_inds = [(i, j) for i, j in it.product(inds, (0, 1, 2))]

    funcs = {
        2: lambda coords: redund.calc_stretch(coords, inds, grad=True),
        3: lambda coords: redund.calc_bend(coords, inds, grad=True),
        4: lambda coords: redund.calc_dihedral(coords, inds, grad=True),
    }
    func = funcs[len(inds)]
    B_grads = list()
    for grad_atom_ind, grad_ax_ind in displacement_inds:
        # Calculate the derivative of an entry of the Wilson B-matrix.
        for atom_ind, ax_ind in displacement_inds:
            plus = coords3d.copy()
            plus[atom_ind, ax_ind] += delta
            _, plus_val = func(plus)
            plus_val = plus_val.reshape(-1, 3)
            minus = coords3d.copy()
            minus[atom_ind, ax_ind] -= delta
            _, minus_val = func(minus)
            minus_val = minus_val.reshape(-1, 3)
            # Select the appropriate item of the primitive internal gradient
            B_grad = (plus_val[grad_atom_ind, grad_ax_ind]
                      - minus_val[grad_atom_ind, grad_ax_ind]) / (2 * delta)
            B_grads.append(B_grad)
    B_grads = np.array(B_grads)
    return B_grads


def test_geom(geom):
    # Recreate the geometry in the correct coordinate system
    geom = Geometry(geom.atoms, geom.cart_coords, coord_type="redund")
    c3d = geom.coords3d
    rc = geom.internal

    ref_funcs = {
        2: lambda coords: d2q_b(*coords),
        3: lambda coords: d2q_a(*coords),
        4: lambda coords: d2q_d(*coords),
    }

    for prim in geom.internal._prim_internals:
        # Wilson B-matrix
        prim_grad = prim_findiff(prim, c3d, rc)
        np.testing.assert_allclose(prim_grad.flatten(), prim.grad)

        # Derivatives of the Wilson B-matrix
        B_grads_ref = ref_funcs[len(prim.inds)](c3d[prim.inds].flatten())
        B_grad = B_findiff(prim, c3d, rc, delta=1e-6)
        np.testing.assert_allclose(B_grad, B_grads_ref, atol=1e-8)
