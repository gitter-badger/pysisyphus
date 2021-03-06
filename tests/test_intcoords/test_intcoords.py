#!/usr/bin/env python3

import numpy as np
import pytest
from pytest import approx

from pysisyphus.calculators.PySCF import PySCF
from pysisyphus.calculators import XTB
from pysisyphus.helpers import geom_loader
from pysisyphus.intcoords.PrimTypes import PrimTypes
from pysisyphus.intcoords.setup import get_fragments
from pysisyphus.intcoords.valid import check_typed_prims
from pysisyphus.io.zmat import geom_from_zmat_str
from pysisyphus.optimizers.RFOptimizer import RFOptimizer
from pysisyphus.testing import using


def numhess(geom, step_size=0.0001):
    coords = geom.coords
    cnum = len(coords)
    H = list()
    for i in range(cnum):
        print(f"Step {i+1}/{cnum}")
        step = np.zeros_like(coords)
        step[i] += step_size

        # Plus
        pl_coords = coords + step
        geom.coords = pl_coords
        pl_forces = geom.forces

        # Minus
        min_coords = coords - step
        geom.coords = min_coords
        min_forces = geom.forces

        fd = -(pl_forces - min_forces) / (2 * step_size)
        H.append(fd)
    H = np.array(H)
    # Symmetrize
    H = (H + H.T) / 2
    return H


def compare_hessians(ref_H, num_H, ref_rms):
    print("Reference hessian")
    print(ref_H)
    print("Findiff hessian")
    print(num_H)

    rms = np.sqrt(np.mean((ref_H - num_H) ** 2))
    print(f"rms(diff)={rms:.8f}")

    return rms == approx(ref_rms, abs=1e-6)


@using("pyscf")
@pytest.mark.parametrize(
    "xyz_fn, coord_type, ref_rms",
    [
        ("lib:hcn_bent.xyz", "cart", 1.2e-6),
        ("lib:h2o2_rot2.xyz", "redund", 0.00085819),
    ],
)
def test_numhess(xyz_fn, coord_type, ref_rms):
    geom = geom_loader(xyz_fn, coord_type=coord_type)

    # Interestingly enough the test will fail with keep_chk == True ...
    # as the RMS value will be much higher
    calc = PySCF(basis="321g", pal=2, keep_chk=False)
    geom.set_calculator(calc)

    H = geom.hessian
    nH = numhess(geom)

    assert compare_hessians(H, nH, ref_rms)


def test_get_fragments():
    geom = geom_loader("lib:thr75_from_1bl8.xyz")

    fragments = get_fragments(geom.atoms, geom.coords3d)
    assert len(fragments) == 4


@using("pyscf")
def test_backtransform_hessian():
    geom = geom_loader("lib:azetidine_hf_321g_opt.xyz", coord_type="redund")

    H_fn = "H"
    cH_fn = "cH"
    f_fn = "f"
    cf_fn = "cf"

    calc = PySCF(basis="321g", pal=2)
    geom.set_calculator(calc)
    f = geom.forces
    np.savetxt(f_fn, f)
    cf = geom.cart_forces
    np.savetxt(cf_fn, cf)
    H = geom.hessian
    np.savetxt(H_fn, H)
    cH = geom.cart_hessian
    np.savetxt(cH_fn, cH)

    f_ref = np.loadtxt(f_fn)
    cf_ref = np.loadtxt(cf_fn)
    H_ref = np.loadtxt(H_fn)
    cH_ref = np.loadtxt(cH_fn)

    # norm = np.linalg.norm(cf_ref)
    # print(f"norm(cart. forces)={norm:.6f}")

    int_ = geom.internal
    int_gradient_ref = -f_ref
    H = int_.transform_hessian(cH_ref, int_gradient_ref)
    np.testing.assert_allclose(H, H_ref)

    cH = int_.backtransform_hessian(H, int_gradient_ref)
    np.testing.assert_allclose(cH, cH_ref, atol=1.5e-7)


def check_typed_prims_for_geom(geom, typed_prims=None):
    int_ = geom.internal
    if typed_prims is None:
        typed_prims = int_.typed_prims
    valid_typed_prims = check_typed_prims(
        geom.coords3d,
        typed_prims,
        int_.bend_min_deg,
        int_.dihed_max_deg,
        int_.lb_min_deg,
    )
    return valid_typed_prims


def test_check_typed_prims():
    geom = geom_loader("lib:h2o2_hf_321g_opt.xyz", coord_type="redund")
    int_ = geom.internal
    typed_prims = int_.typed_prims
    valid_typed_prims = check_typed_prims_for_geom(geom)
    assert typed_prims == valid_typed_prims


def test_check_typed_prims_invalid_bend():
    geom_kwargs = {
        "coord_type": "redund",
    }
    h2o_zmat = """O
    H 1 0.96
    H 1 0.96 2 104.5
    """
    geom = geom_from_zmat_str(h2o_zmat, **geom_kwargs)
    typed_prims = geom.internal.typed_prims
    bend = typed_prims[2]
    assert bend[0] == PrimTypes.BEND

    h2o_linear_zmat = """O
    H 1 0.96
    H 1 0.96 2 180.0
    """
    geom_linear = geom_from_zmat_str(h2o_linear_zmat, **geom_kwargs)

    # Angle should now be invalid at linear coordinates
    valid_typed_prims = check_typed_prims_for_geom(geom_linear, typed_prims)
    assert bend not in valid_typed_prims


def test_check_typed_prims_invalid_dihedral():
    geom_kwargs = {
        "coord_type": "redund",
    }
    h2o2_zmat = """O
    O 1 1.5
    H 1 1.07 2 109.5
    H 2 1.07 1 109.5 3 180.
    """
    geom = geom_from_zmat_str(h2o2_zmat, **geom_kwargs)
    typed_prims = geom.internal.typed_prims
    bend013 = typed_prims[4]
    dihedral = typed_prims[-1]
    assert bend013[0] == PrimTypes.BEND
    assert dihedral[0] == PrimTypes.PROPER_DIHEDRAL

    h2o2_linear_zmat = """O
    O 1 1.5
    H 1 1.07 2 109.5
    H 2 1.07 1 178 3 180.
    """
    geom_linear = geom_from_zmat_str(h2o2_linear_zmat, **geom_kwargs)

    # Bend and dihedral should now be invalid at linear coordinates
    valid_typed_prims = check_typed_prims_for_geom(geom_linear, typed_prims)
    assert bend013 not in valid_typed_prims
    assert dihedral not in valid_typed_prims


def test_linear_dihedrals():
    geom = geom_loader("lib:dihedral_gen_test.cjson", coord_type="redund")
    typed_prims = geom.internal.typed_prims
    pd = PrimTypes.PROPER_DIHEDRAL
    need_diheds = ((2, 7, 0, 5), (2, 7, 0, 4), (3, 7, 0, 4), (2, 7, 0, 5))
    for dihed in need_diheds:
        assert ((pd, *dihed) in typed_prims) or ((pd, *dihed[::-1]) in typed_prims)


@using("xtb")
def test_opt_linear_dihedrals():
    geom = geom_loader("lib:dihedral_gen_test.cjson", coord_type="redund")
    geom.set_calculator(XTB())

    opt_kwargs = {
        "thresh": "gau_tight",
    }
    opt = RFOptimizer(geom, **opt_kwargs)
    opt.run()

    assert opt.is_converged
    assert opt.cur_cycle == 16
    assert geom.energy == pytest.approx(-10.48063133)
