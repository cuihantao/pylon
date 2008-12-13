#------------------------------------------------------------------------------
# Copyright (C) 2008 Richard W. Lincoln
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 dated June, 1991.
#
# This software is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANDABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#------------------------------------------------------------------------------

""" Test case for the AC Power Flow routine. """

#------------------------------------------------------------------------------
#  Imports:
#------------------------------------------------------------------------------

from os.path import join, dirname
from unittest import TestCase, main

from pylon.readwrite.api import read_matpower
from pylon.routine.api import NewtonPFRoutine

#------------------------------------------------------------------------------
#  Constants:
#------------------------------------------------------------------------------

DATA_FILE = join(dirname(__file__), "data/case6ww.m")

#------------------------------------------------------------------------------
#  "ACPFTest" class:
#------------------------------------------------------------------------------

class ACPFTest(TestCase):
    """ We use a MATPOWER data file and validate the results against those
    obtained from running the MATPOWER runacpf.m script with the same data
    file. See reader_test_case.py for validation of MATPOWER data file parsing.

    """

    routine = NewtonPFRoutine

    def setUp(self):
        """ The test runner will execute this method prior to each test. """

        network = read_matpower(DATA_FILE)
        self.routine = NewtonPFRoutine(network)


    def test_voltage_vector(self):
        """ Test the initial vector of complex bus voltages.

        V0 =

            1.0500
            1.0500
            1.0700
            1.0000
            1.0000
            1.0000

        """

        self.routine._initialise_voltage_vector()
        v_initial = self.routine.v

        self.assertEqual(v_initial.typecode, "z")
        self.assertEqual(v_initial.size, (6, 1))

        places = 4

        # TODO: Repeat test for a network with generator voltage set points
        # different to the initial bus voltage magnitudes.
        v0_0 = 1.0500
        v0_2 = 1.0700
        v0_5 = 1.0000

        self.assertAlmostEqual(abs(v_initial[0]), v0_0, places)
        self.assertAlmostEqual(abs(v_initial[2]), v0_2, places)
        self.assertAlmostEqual(abs(v_initial[5]), v0_5, places)


    def test_apparent_power_vector(self):
        """ Test the vector of complex bus power injections.

        Sbus =

                0
           0.5000
           0.6000
          -0.7000 - 0.7000i
          -0.7000 - 0.7000i
          -0.7000 - 0.7000i

        """

        self.routine.solve()
        s_surplus = self.routine.s_surplus

        self.assertEqual(s_surplus.typecode, "z")
        self.assertEqual(s_surplus.size, (6, 1))

        places = 4

        s_0 = 0.0000
        s_2 = 0.6000
        s_35 = -0.7000

        self.assertAlmostEqual(abs(s_surplus[0]), s_0, places)
        self.assertAlmostEqual(abs(s_surplus[2]), s_2, places)
        self.assertAlmostEqual(s_surplus[3].real, s_35, places)
        self.assertAlmostEqual(s_surplus[3].imag, s_35, places)
        self.assertAlmostEqual(s_surplus[5].real, s_35, places)
        self.assertAlmostEqual(s_surplus[5].imag, s_35, places)


    def test_function_evaluation(self):
        """ Test function evaluation without iteration.

        F =

           -0.1718
           -0.3299
            0.4412
            0.5061
            0.4874
           -0.0053
            0.0274
           -0.2608

        """

        # Perform preliminary steps
        self.routine._make_admittance_matrix()
        self.routine._initialise_voltage_vector()
        self.routine._make_apparent_power_injection_vector()
        self.routine._index_buses()

        self.routine._evaluate_function()
        f = self.routine.f

        self.assertEqual(f.size, (8, 1))

        places = 4

        f_0 = -0.1718
        f_6 = 0.0274

        self.assertAlmostEqual(f[0], f_0, places)
        self.assertAlmostEqual(f[6], f_6, places)


    def test_convergence_check(self):
        """ Test convergence satisfaction check.

        normF =

            0.5061

        """

        routine = self.routine

        # Perform preliminary steps
        routine._make_admittance_matrix()
        routine._initialise_voltage_vector()
        routine._make_apparent_power_injection_vector()
        routine._index_buses()
        routine._evaluate_function()

        # True negative
        routine.converged = False
        routine.tolerance = 0.500
        self.assertFalse(routine._check_convergence())

        # True positive
        routine.converged = False
        routine.tolerance = 0.510
        self.assertTrue(routine._check_convergence())


    def test_bus_indexing(self):
        """ Test the indexing of buses according their mode.

        ref =

            1

        pv_bus =

            2
            3

        pq_bus =

            4
            5
            6

        pvpq_bus =

            2
            3
            4
            5
            6

        """

        routine = self.routine

        routine._index_buses()

        self.assertEqual(routine.pv_idxs.size, (2, 1))
        self.assertEqual(routine.pq_idxs.size, (3, 1))
        self.assertEqual(routine.pvpq_idxs.size, (5, 1))

        pv_0 = 1
        pq_2 = 5
        pvpq_3 = 4

        self.assertEqual(routine.pv_idxs[0], pv_0)
        self.assertEqual(routine.pq_idxs[2], pq_2)
        self.assertEqual(routine.pvpq_idxs[3], pvpq_3)


    def test_jacobian(self):
        """ Test creation of the Jacobian matrix.

        dS_dVm[0] =

           4.3070 +12.6527i  -2.1000 - 4.2000i        0            -1.2353 - 4.9412i  -0.8714 - 3.2676i        0
          -2.1000 - 4.2000i  10.1072 +24.9408i  -0.8077 - 4.0385i  -4.2000 - 8.4000i  -1.0500 - 3.1500i  -1.6370 - 4.6771i
                0            -0.8231 - 4.1154i   4.6991 +18.6294i        0            -1.5659 - 3.3927i  -2.0577 -10.2885i
          -1.1765 - 4.7059i  -4.0000 - 8.0000i        0             5.9176 +13.9306i  -1.0000 - 2.0000i        0
          -0.8299 - 3.1120i  -1.0000 - 3.0000i  -1.4634 - 3.1707i  -1.0000 - 2.0000i   5.0994 +13.4652i  -1.0000 - 3.0000i
                0            -1.5590 - 4.4543i  -1.9231 - 9.6154i        0            -1.0000 - 3.0000i   4.2695 +16.0439i

        dS_dVa[0] =

          12.6188 - 4.3117i  -4.4100 + 2.2050i        0            -4.9412 + 1.2353i  -3.2676 + 0.8714i         0
          -4.4100 + 2.2050i  24.9582 - 9.9562i  -4.3212 + 0.8642i  -8.4000 + 4.2000i  -3.1500 + 1.0500i  -4.6771 + 1.6370i
                0            -4.3212 + 0.8642i  18.0023 - 4.4878i        0            -3.3927 + 1.5659i -10.2885 + 2.0577i
          -4.9412 + 1.2353i  -8.4000 + 4.2000i        0            15.3412 - 6.4353i  -2.0000 + 1.0000i        0
          -3.2676 + 0.8714i  -3.1500 + 1.0500i  -3.3927 + 1.5659i  -2.0000 + 1.0000i  14.8103 - 5.4872i  -3.0000 + 1.0000i
                0            -4.6771 + 1.6370i -10.2885 + 2.0577i        0            -3.0000 + 1.0000i  17.9655 - 4.6947i


        dS_dVm =
            [-1.22e+01+j4.52e+00  4.20e+00-j2.10e+00          0           4.94e+00-j1.24e+00  3.27e+00-j8.71e-01          0         ]
            [ 4.20e+00-j2.10e+00 -2.40e+01+j1.04e+01  4.04e+00-j8.08e-01  8.40e+00-j4.20e+00  3.15e+00-j1.05e+00  4.68e+00-j1.64e+00]
            [         0           4.12e+00-j8.23e-01 -1.75e+01+j5.35e+00          0           3.39e+00-j1.57e+00  1.03e+01-j2.06e+00]
            [ 4.71e+00-j1.18e+00  8.00e+00-j4.00e+00          0          -1.49e+01+j5.47e+00  2.00e+00-j1.00e+00          0         ]
            [ 3.11e+00-j8.30e-01  3.00e+00-j1.00e+00  3.17e+00-j1.46e+00  2.00e+00-j1.00e+00 -1.43e+01+j4.62e+00  3.00e+00-j1.00e+00]
            [         0           4.45e+00-j1.56e+00  9.62e+00-j1.92e+00          0           3.00e+00-j1.00e+00 -1.72e+01+j3.52e+00]

        dS_dVa =
            [ 1.26e+01-j4.31e+00 -4.41e+00+j2.21e+00          0          -4.94e+00+j1.24e+00 -3.27e+00+j8.71e-01          0         ]
            [-4.41e+00+j2.21e+00  2.50e+01-j9.96e+00 -4.32e+00+j8.64e-01 -8.40e+00+j4.20e+00 -3.15e+00+j1.05e+00 -4.68e+00+j1.64e+00]
            [         0          -4.32e+00+j8.64e-01  1.80e+01-j4.49e+00          0          -3.39e+00+j1.57e+00 -1.03e+01+j2.06e+00]
            [-4.94e+00+j1.24e+00 -8.40e+00+j4.20e+00          0           1.53e+01-j6.44e+00 -2.00e+00+j1.00e+00          0         ]
            [-3.27e+00+j8.71e-01 -3.15e+00+j1.05e+00 -3.39e+00+j1.57e+00 -2.00e+00+j1.00e+00  1.48e+01-j5.49e+00 -3.00e+00+j1.00e+00]
            [         0          -4.68e+00+j1.64e+00 -1.03e+01+j2.06e+00          0          -3.00e+00+j1.00e+00  1.80e+01-j4.69e+00]

        J11[0] =

           24.9582   -4.3212   -8.4000   -3.1500   -4.6771
           -4.3212   18.0023         0   -3.3927  -10.2885
           -8.4000         0   15.3412   -2.0000         0
           -3.1500   -3.3927   -2.0000   14.8103   -3.0000
           -4.6771  -10.2885         0   -3.0000   17.9655


        J12[0] =

           -4.2000   -1.0500   -1.6370
                 0   -1.5659   -2.0577
            5.9176   -1.0000         0
           -1.0000    5.0994   -1.0000
                 0   -1.0000    4.2695

        J21[0] =

            4.2000         0   -6.4353    1.0000         0
            1.0500    1.5659    1.0000   -5.4872    1.0000
            1.6370    2.0577         0    1.0000   -4.6947


        J22[0] =

           13.9306   -2.0000         0
           -2.0000   13.4652   -3.0000
                 0   -3.0000   16.0439


        J[0] =

           24.9582   -4.3212   -8.4000   -3.1500   -4.6771   -4.2000   -1.0500   -1.6370
           -4.3212   18.0023         0   -3.3927  -10.2885         0   -1.5659   -2.0577
           -8.4000         0   15.3412   -2.0000         0    5.9176   -1.0000         0
           -3.1500   -3.3927   -2.0000   14.8103   -3.0000   -1.0000    5.0994   -1.0000
           -4.6771  -10.2885         0   -3.0000   17.9655         0   -1.0000    4.2695
            4.2000         0   -6.4353    1.0000         0   13.9306   -2.0000         0
            1.0500    1.5659    1.0000   -5.4872    1.0000   -2.0000   13.4652   -3.0000
            1.6370    2.0577         0    1.0000   -4.6947         0   -3.0000   16.0439

        J12 =
            [ 8.40e+00  3.15e+00  4.68e+00]
            [    0      3.39e+00  1.03e+01]
            [-1.49e+01  2.00e+00     0    ]
            [ 2.00e+00 -1.43e+01  3.00e+00]
            [    0      3.00e+00 -1.72e+01]

        J22 =
            [ 5.47e+00 -1.00e+00     0    ]
            [-1.00e+00  4.62e+00 -1.00e+00]
            [    0     -1.00e+00  3.52e+00]

        J =

        [ 2.50e+01 -4.32e+00 -8.40e+00 -3.15e+00 -4.68e+00  8.40e+00  3.15e+00 ... ]
        [-4.32e+00  1.80e+01     0     -3.39e+00 -1.03e+01     0      3.39e+00 ... ]
        [-8.40e+00     0      1.53e+01 -2.00e+00     0     -1.49e+01  2.00e+00 ... ]
        [-3.15e+00 -3.39e+00 -2.00e+00  1.48e+01 -3.00e+00  2.00e+00 -1.43e+01 ... ]
        [-4.68e+00 -1.03e+01     0     -3.00e+00  1.80e+01     0      3.00e+00 ... ]
        [ 4.20e+00     0     -6.44e+00  1.00e+00     0      5.47e+00 -1.00e+00 ... ]
        [ 1.05e+00  1.57e+00  1.00e+00 -5.49e+00  1.00e+00 -1.00e+00  4.62e+00 ... ]
        [ 1.64e+00  2.06e+00     0      1.00e+00 -4.69e+00     0     -1.00e+00 ... ]

        """

        routine = self.routine

        routine._make_admittance_matrix()
        routine._initialise_voltage_vector()
        routine._make_apparent_power_injection_vector()
        routine._index_buses()

        J = routine._make_jacobian()

        self.assertEqual(J.size, (8, 8))

        places = 4

        J0_0 = 24.9582
        J6_3 = -5.4872
        J3_6 = 5.0994
        J7_1 = 2.0577
        J0_7 = -1.6370
        J6_7 = -3.0000

        self.assertAlmostEqual(J[0, 0], J0_0, places)
        self.assertAlmostEqual(J[6, 3], J6_3, places)
        self.assertAlmostEqual(J[3, 6], J3_6, places)
        self.assertAlmostEqual(J[7, 1], J7_1, places)
        self.assertAlmostEqual(J[0, 7], J0_7, places)
        self.assertAlmostEqual(J[6, 7], J6_7, places)


    def test_iteration(self):
        """ Test iteration of full Newton's method. """

        routine = self.routine

        routine._make_admittance_matrix()
        routine._initialise_voltage_vector()
        routine._make_apparent_power_injection_vector()
        routine._index_buses()

        # Initial evaluation of f(x0) and convergency check
#        self.converged = False
#        self._evaluate_function()
#        self._check_convergence()

#        routine.iterate()


if __name__ == "__main__":
    import logging, sys
    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.setLevel(logging.DEBUG)

    main()

# EOF -------------------------------------------------------------------------