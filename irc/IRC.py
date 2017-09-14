#!/usr/bin/env python3

import copy
import logging
import pathlib

import numpy as np

np.set_printoptions(suppress=True, precision=4)

# https://verahill.blogspot.de/2013/06/439-calculate-frequencies-from-hessian.html
# https://chemistry.stackexchange.com/questions/74639


class IRC:

    def __init__(self, geometry, step_length=0.1, max_steps=10,
                 forward=False, backward=False, energy_lowering=2.5e-4):
        assert(step_length > 0), "step_length has to be > 0"

        self.geometry = geometry
        self.step_length = step_length
        self.max_steps = max_steps
        self.forward = not backward
        self.backward = not forward
        self.energy_lowering = energy_lowering

        # Backup TS data
        self.ts_coords = copy.copy(self.geometry.coords)
        self.ts_energy = copy.copy(self.geometry.energy)
        self.ts_hessian = copy.copy(self.geometry.hessian)

        self.init_displ = self.initial_displacement()

    def prepare(self, direction):
        self.cur_step = 0
        # Over the course of the IRC the hessian usually gets updated.
        # Copying the TS hessian here ensures a clean start in combined
        # forward and backward runs. Otherwise at the beginning of a
        # backward run following a forward run self.hessian would be
        # the hessian at the end of the forward run.
        self.hessian = self.ts_hessian

        # Do inital displacement from the TS
        init_factor = 1 if (direction == "forward") else -1
        initial_step = init_factor*self.init_displ
        self.geometry.coords = self.ts_coords + initial_step
        initial_step_length = np.linalg.norm(initial_step)
        logging.info(f"Did inital step of {initial_step_length:.4f} "
                      "from the TS.")
        self.irc_energies = [self.ts_energy]

    def initial_displacement(self):
        """Returns a step length in angstrom to perfom an inital displacement
        from the TS."""
        mm_sqr_inv = self.geometry.mm_sqrt_inv
        eigvals, eigvecs = np.linalg.eig(self.geometry.mw_hessian)

        # Find smallest eigenvalue to get the imaginary mode
        logging.warning("Only considering smallest eigenvalue for now!")
        eigval_min = np.min(eigvals)
        img_index = np.where(eigvals == eigval_min)[0][0]
        logging.info(f"Smallest eigenvalue: {eigval_min}, index {img_index}")
        """
        # Zero small eigenvalues
        eigvals = np.abs(eigvals)
        all_indices = np.arange(eigvals.size)
        keep_indices = eigvals > 1e-4
        freqs = np.sqrt(eigvals[keep_indices])
        # We determine img_index before we cut the arrays. Imagine the inital
        # img_index would be 4, but after cutting the small eigenvalues there
        # are only 3 eigenvalues/eigenvectors left. Than the imaginary mode
        # couldn be accessed anymore.
        assert(img_index < freqs.size)
        # Flip sign on the imaginary eigenvalue
        freqs[img_index] *= -1
        print("Frequencies:")
        for i, f in enumerate(freqs):
            print(f"{i}: {f}")
        """

        # Calculate cartesian displacement vectors. Right now the eigenvectors
        # are mass-weighted.
        cart_displs = [mm_sqr_inv.dot(nm) for nm in eigvecs.transpose()]
        cart_displs = [cd/np.linalg.norm(cd) for cd in cart_displs]
        self.transition_vector = cart_displs[img_index]
        """
        print("Cartesian displacement vectors, normalized:")
        for i, cd in enumerate(cart_displs):
            print(f"{i}: {cd}")
        """
        # Calculate the length of the initial step away from the TS to initiate
        # the IRC/MEP. We assume a quadratic potential and calculate the
        # displacement for a given energy lowering.
        # dE = (k*dq**2)/2 (dE = energy lowering, k = eigenvalue corresponding
        # to the transition vector/imaginary mode, dq = step length)
        # dq = sqrt(dE*2/k)
        # See 10.1021/ja00295a002 and 10.1063/1.462674
        step_length = np.sqrt(self.energy_lowering*2
                              / np.abs(eigvals[img_index])
        )

        return step_length*self.transition_vector

    def irc(self):
        irc_coords = list()
        while True:
            if self.cur_step == self.max_steps:
                print("IRC steps exceeded. Stopping.")
                print()
                break

            print(f"IRC step {self.cur_step+1} out of {self.max_steps}")
            # Do macroiteration/IRC step
            irc_coords.append(self.geometry.coords)
            self.step()
            last_energy = self.irc_energies[-2]
            this_energy = self.irc_energies[-1]
            if (this_energy > last_energy):
                print("Energy increased!")
                print()
                break
            elif abs(last_energy - this_energy) <= 1e-5:
                print("Energy converged!")
                print()
                break
            self.cur_step += 1
            print()

        # Don't return the TS energy we added at the beginning
        return irc_coords, self.irc_energies[1:]

    def run(self):
        self.all_coords = list()
        self.all_energies = list()

        if self.forward:
            logging.info("IRC forward")
            self.prepare("forward")
            forward_coords, forward_energies = self.irc()
            self.all_coords.extend(forward_coords[::-1])
            self.all_energies.extend(forward_energies[::-1])
            self.forward_step = self.cur_step

        # Add TS data
        self.all_coords.append(self.ts_coords)
        self.all_energies.append(self.ts_energy)

        if self.backward:
            logging.info("IRC backward")
            self.prepare("backward")
            backward_coords, backward_energies = self.irc()
            self.all_coords.extend(backward_coords)
            self.all_energies.extend(backward_energies)
            self.backward_step = self.cur_step

        self.all_coords = np.array(self.all_coords)
        self.all_energies = np.array(self.all_energies)
        self.postprocess()

    def postprocess(self):
        pass

    def write_trj(self, path):
        path = pathlib.Path(path)
        xyz_strings = list()
        for coords, energy in zip(self.all_coords, self.all_energies):
            self.geometry.coords = coords
            # Use energy as comment
            as_xyz = self.geometry.as_xyz(energy)
            xyz_strings.append(as_xyz)

        xyzs_joined = "\n".join(xyz_strings)
        with open(path / "irc.trj", "w") as handle:
            handle.write(xyzs_joined)

        np.savetxt(path / "irc_energies", self.all_energies)

