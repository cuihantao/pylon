#------------------------------------------------------------------------------
# Copyright (C) 2010 Richard Lincoln
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

""" DC Optimal Power Flow for routine.

    References:
        Ray Zimmerman, "dcopf.m", MATPOWER, PSERC Cornell, version 3.2,
        http://www.pserc.cornell.edu/matpower/, June 2007
"""

#------------------------------------------------------------------------------
#  Imports:
#------------------------------------------------------------------------------

import logging
from time import time

from math import pi

from cvxopt.base import matrix, spmatrix, sparse, spdiag
from cvxopt import solvers
from cvxopt.solvers import qp, lp

from pylon import PW_LINEAR, POLYNOMIAL, REFERENCE

#------------------------------------------------------------------------------
#  Constants:
#------------------------------------------------------------------------------

QUADRATIC = "quadratic"
LINEAR = "linear"

#------------------------------------------------------------------------------
#  Logging:
#------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

#------------------------------------------------------------------------------
#  "DCOPF" class:
#------------------------------------------------------------------------------

class DCOPF(object):
    """ A method class for solving the DC optimal power flow problem

        References:
            Ray Zimmerman, "dcopf.m", MATPOWER, PSERC Cornell, version 3.2,
            http://www.pserc.cornell.edu/matpower/, June 2007
    """

    #--------------------------------------------------------------------------
    #  "object" interface:
    #--------------------------------------------------------------------------

    def __init__(self, case, solver=None, show_progress=True,
            max_iterations=100, absolute_tol=1e-7, relative_tol=1e-6,
            feasibility_tol=1e-7):
        """ Initialises the new DCOPF instance.
        """
        # Case to be optimised.
        self.case = case

        # Choice of solver (May be None or "mosek" (or "glpk" for linear
        # formulation)). Specify None to use the Python solver from CVXOPT.
        self.solver = solver

        # Turns the output to the screen on or off.
        self.show_progress = show_progress
        # Maximum number of iterations.
        self.max_iterations = max_iterations
        # Absolute accuracy.
        self.absolute_tol = absolute_tol
        # Relative accuracy.
        self.relative_tol = relative_tol
        # Tolerance for feasibility conditions.
        self.feasibility_tol = feasibility_tol

        # Solution dict from CVXOPT.
        self._solution = {}

        # Objective function value (total system cost $/h).
        self._f = 0.0


    def solve(self):
        """ Solves a DC OPF.
        """
        logger.info("Solving DC OPF [%s]." % self.case.name)

        # Set the parameters of the CVXOPT algorithm.
        self._algorithm_parameters()

        # Retrieve the contents of the case.
        b, l, g, nb, nl, ng, base_mva = self._unpack_case(self.case)

        # Zero result attributes.
        self.case.reset()

        # Start the clock.
        t0 = time()

        # Build the B matrices and phase shift injection vectors.
        B, Bf, Pbusinj, Pfinj = self.case.Bdc

        # Determine if a linear formulation of the problem may be used.
        lin = self._linear_formulation(g)

        # Get the initial x vector where AA * x <= bb.
        x0 = self._initial_x(b, g, base_mva, lin)

        # Problem constraints.
        Acc, bcc = self._generator_cost(g, nb, ng, base_mva, lin)
        Aref, bref = self._reference_angle(b, g, nb, ng, lin)
        Amis, bmis = self._power_balance(B, Pbusinj, b, g, nb, ng,base_mva,lin)
        Agen, bgen = self._generation_limit(g, nb, ng, base_mva, lin)
        Aflow, bflow = self._branch_flow(Bf, Pfinj, g, ng, l, nl, base_mva,lin)

        # Combine the equality and inequality constraints.
        Aeq = sparse([Aref, Amis])
        beq = matrix([bref, bmis])
        Aieq = sparse([Agen, Acc, Aflow])
        bieq = matrix([bgen, bcc, bflow])

        # The objective function has the form 0.5 * x'*H*x + c'*x.
        H, c = self._objective_function(g, nb, ng, base_mva, lin)

        # Solve the problem.
        solution = self._solve_program(H, c, Aieq, bieq, Aeq, beq, x0, lin)

        # Compute elapsed time.
        t_elapsed = time() - t0

        return self._process_solution(Bf, b, l, g, nb, nl, ng, base_mva,
                                      solution, t_elapsed)


    def _algorithm_parameters(self):
        """ Sets the parameters of the CVXOPT solver algorithm.
        """
        solvers.options["show_progress"] = self.show_progress
        solvers.options["maxiters"] = self.max_iterations
        solvers.options["abstol"] = self.absolute_tol
        solvers.options["reltol"] = self.relative_tol
        solvers.options["feastol"] = self.feasibility_tol


    def _unpack_case(self, case):
        """ Returns the contents of the case to be used in the OPF.
        """
        base_mva = self.case.base_mva
        b = self.case.connected_buses
        l = self.case.online_branches
        g = self.case.online_generators
        nb = len(b)
        nl = len(l)
        ng = len(g)

        return b, l, g, nb, nl, ng, base_mva


    def _linear_formulation(self, generators):
        """ Returns true if a linear formulation of the problem may be used.
        """
        models = [g.pcost_model for g in generators]

        if (POLYNOMIAL in models) and (PW_LINEAR in models):
            logger.info("Not all generators use the same cost model, all will "
                "be converted to piece-wise linear.")
            for g in generators:
                g.poly_to_pwl()
            linear = True
        elif POLYNOMIAL not in models:
            linear = True
        elif PW_LINEAR not in models:
            linear = False
        else:
            logger.error("Invalid cost models specified.")

        return linear


    def _initial_x(self, buses, generators, base_mva, linear):
        """ Returns the vector x where, AA * x <= bb.  Stack the initial
            voltage phases for each generator bus, the generator real power
            output and if using pw linear costs, the output cost.
        """
        v_angle = matrix([v.v_angle_guess * pi / 180 for v in buses])

        p_supply = matrix([g.p / base_mva for g in generators])

        x = matrix([v_angle, p_supply])

        p_cost = matrix(0.0, (len(generators), 1))
        if linear:
            for i, g in enumerate(generators):
                p_cost[i] = g.total_cost()
            x = matrix([x, p_cost])

        logger.debug("Initial x vector:\n%s" % x)
        return x


    def _generator_cost(self, generators, nb, ng, base_mva, linear):
        """ Set up constraint matrix AA where, AA * x <= bb

            For pw linear cost models include a constraint for each
            segment of the function. For polynomial (quadratic) models
            just add an appropriately sized empty matrix.
        """
        if linear: # pw cost constraints
            # A list of the number of cost constraints for each generator
            n_seg = [len(g.p_cost) - 1 for g in generators]
            # The total number of cost constraints (for matrix sizing)
            n_cc = sum(n_seg)
            # The total number of cost variables.
            n_cost = len(generators)

            Asize = (n_cc, nb + ng + n_cost)
            Acc = spmatrix([], [], [], size=Asize, tc='d')

            bcc = matrix(0.0, size=(n_cc, 1))

            i_segment = 0 # Counter of total segments processed.
            for i, g in enumerate(generators):
                for j in range(n_seg[i]):
                    x1, y1 = g.p_cost[j]
                    x2, y2 = g.p_cost[j + 1]

                    m = (y2 - y1) / (x2 - x1) # segment gradient
                    c = y1 - m * x1 # segment y-intercept

                    Acc[i_segment + j, nb + i] = m * base_mva
                    Acc[i_segment + j, nb + ng + i] = -1.0
                    bcc[i_segment + j] = -c

                i_segment += n_seg[i]

#            Acc[:, n_buses + n_generators:] = -1.0
        else:
            Acc = spmatrix([], [], [], size=(0, nb + ng))
            bcc = matrix([], size=(0, 1))

        logger.debug("Cost constraint matrix:\n%s" % Acc)
        logger.debug("Cost constraint vector:\n%s" % bcc)

        return Acc, bcc


    def _reference_angle(self, buses, generators, nb, ng, linear):
        """ Use the slack bus angle for reference or buses[0].
        """
        # Indices of slack buses
        refs = matrix([i for i, v in enumerate(buses)
                           if v.type == REFERENCE])

        if not len(refs) == 1:
            logger.error("OPF requires a single reference bus.")
            return None

        # Append zeros for piecewise linear cost constraints
        if linear:
            n_cost = ng#len([g.total_cost() for g in generators])
        else:
            n_cost = 0

        a_ref = spmatrix([], [], [], size=(1, nb + ng + n_cost))
        a_ref[0, refs] = 1

        b_ref = matrix([buses[refs[0]].v_angle_guess])

        logger.debug("Reference angle matrix:\n%s" % a_ref)
        logger.debug("Reference angle vector:\n%s" % b_ref)

        return a_ref, b_ref

    #--------------------------------------------------------------------------
    #  Active power flow equations:
    #--------------------------------------------------------------------------

    def _power_balance(self, B, Pbusinj, buses, generators, nb, ng,
                       base_mva, linear):
        """ P mismatch (B*Va + Pg = Pd).
        """
        # Bus-(online)generator incidence matrix.
        i_busgen = spmatrix([],[],[], size=(nb, ng))

        j = 0
        for g in generators:
            i_busgen[buses.index(g.bus), j] = 1.0
            j += 1

        # Include zero matrix for pw linear cost constraints.
        nc = ng if linear else 0

        c_mis = spmatrix([], [], [], size=(nb, nc))

        # sparse() does vstack, to hstack we transpose.
        Amis = sparse([B.T, -i_busgen.T, c_mis.T]).T

        logger.debug("Power balance matrix:\n%s" % Amis)

        Pd = matrix([v.p_demand for v in buses])
        Gs = matrix([v.g_shunt for v in buses])

        bmis = -((Pd + Gs) / base_mva) - Pbusinj

        logger.debug("Power balance vector:\n%s" % bmis)

        return Amis, bmis

    #--------------------------------------------------------------------------
    #  Active power generation limit constraints:
    #--------------------------------------------------------------------------

    def _generation_limit(self, generators, nb, ng, base_mva, linear):
        """ Returns the lower and upper limits on generator output.
        """
        # All zero sparse matrix to exclude voltage angles.
        Av = spmatrix([], [], [], size=(ng, nb))

        Igen = spdiag(matrix(1.0, (ng, 1)))

        # Number of cost variables (n_generators or zero).
        nc = ng if linear else 0

        Acost = spmatrix([], [], [], (ng, nc))

        # The identity matrix made negative to turn the inequality
        # contraint into >=.
        Al = sparse([[Av], [-Igen], [Acost]])
        Au = sparse([[Av], [ Igen], [Acost]])

        Agen = sparse([Al, Au])

        logger.debug("Generator limit matrix:\n%s" % Agen)


        bl = matrix([-g.p_min / base_mva for g in generators])
        bu = matrix([ g.p_max / base_mva for g in generators])

        bgen = matrix([bl, bu])

        logger.debug("Generator limit vector:\n%s" % bgen)

        return Agen, bgen

    #--------------------------------------------------------------------------
    #  Active power flow limits:
    #--------------------------------------------------------------------------

    def _branch_flow(self, Bf, Pfinj, generators, ng, branches, nl,
                     base_mva, linear):
        """ The real power flows at the from end the lines are related to the
            bus voltage angles by Pf = Bf * Va + Pfinj.
        """
        # Number of cost variables (n_generators or zero).
        nc = ng if linear else 0

        # Exclude generation and cost variables from the constraint.
        Agen = spmatrix([], [], [], (nl, ng + nc))

        # Branch 'from' end flow limit.
        Af = sparse([[Bf], [Agen]])
        # Branch 'to' flow limit.
        At = sparse([[-Bf], [Agen]])

        Aflow = sparse([Af, At])

        logger.debug("Flow limit matrix:\n%s" % Aflow)


        rate_a = matrix([e.rate_a for e in branches])
        # From and to limits are both the same.
        bf = rate_a / base_mva - Pfinj
        bt = rate_a / base_mva + Pfinj

        bflow = matrix([bf, bt])

        logger.debug("Flow limit vector:\n%s" % bflow)

        return Aflow, bflow

    #--------------------------------------------------------------------------
    #  Objective function:
    #--------------------------------------------------------------------------

    def _objective_function(self, generators, nb, ng, base_mva, linear):
        """ H is a sparse square matrix.

            The objective function has the form 0.5 * x'*H*x + c'*x

            Quadratic cost function coefficients: c0*x^2 + c1*x + c2
        """
        nc = ng
        if linear:
            dim = nb + ng + nc
            H = spmatrix([], [], [], (dim, dim))

        else:
            coeffs = [g.p_cost for g in generators]

            # Quadratic cost coefficients in p.u.
            c2_coeffs = matrix([c2 * base_mva**2 for c2, _, _ in coeffs])

    #        quad_coeffs = matrix([g.cost_function.c for g in generators])
            # TODO: Find explanation for multiplying by the square
            # of the system base (pu)
#            c_coeffs *= base_mva**2

            # TODO: Explain multiplication of the pu coefficients by 2
            H = spmatrix(2 * c2_coeffs, matrix(range(ng)) + nb,
                                        matrix(range(ng)) + nb,
                                        size=(nb + ng, nb + ng))

        logger.debug("Hessian matrix:\n%s" % H)

        if linear:
            c = matrix([matrix(0.0, (nb + ng, 1)),
                        matrix(1.0, (nc, 1))])
        else:
            v_zeros = matrix(0.0, (nb, 1))

            cost_coeffs = [g.p_cost for g in generators]

            # Linear cost coefficients in p.u.
            c1_coeffs = matrix([c1 * base_mva for _, c1, _ in cost_coeffs])

            c = matrix([v_zeros, c1_coeffs])

        logger.debug("Objective function vector:\n%s" % c)

        return H, c


    def _solve_program(self, H, c, Aieq, b_ieq, Aeq, b_eq, x0, linear):
        """ Solves the formulated program.
        """
        # CVXOPT documentation.
        #
        #Solves the pair of primal and dual linear programs
        #    minimize    c'x
        #    subject to  Gx + s = h
        #                Ax = b
        #                s >= 0
        #
        #    maximize    -h'*z - b'*y
        #    subject to  G'*z + A'*y + c = 0
        #                z >= 0.
        #
        #Input arguments.
        #    G is m x n, h is m x 1, A is p x n, b is p x 1.  G and A must be
        #    dense or sparse 'd' matrices.   h and b are dense 'd' matrices
        #    with one column.  The default values for A and b are empty
        #    matrices with zero rows.
        if linear:
            G, h = Aieq, b_ieq,
            A, b = Aeq, b_eq,
            primalstart = {"x": x0}

            solution = lp(c, G, h, A, b, self.solver)#, primalstart)

#            try:
#                solution = lp(c, G, h, A, b, self.solver)#, primalstart)
#            except ValueError:
#                solution = {"status": "error"}

            logger.debug("Linear solver returned: %s" % solution)


        #Solves a quadratic program
        #    minimize    (1/2)*x'*P*x + q'*x
        #    subject to  G*x <= h
        #                A*x = b.
        #
        #initvals is a dictionary with optional primal and dual starting
        #points initvals['x'], initvals['s'], initvals['y'], initvals['z'].
        #- initvals['x'] is a dense 'd' matrix of size (n,1).
        #- initvals['s'] is a dense 'd' matrix of size (K,1), representing
        #  a vector that is strictly positive with respect to the cone C.
        #- initvals['y'] is a dense 'd' matrix of size (p,1).
        #- initvals['z'] is a dense 'd' matrix of size (K,1), representing
        #  a vector that is strictly positive with respect to the cone C.
        else:
            P, q = H, c
            G, h = Aieq, b_ieq,
            A, b = Aeq, b_eq,
            initvals = {"x": x0}

            solution = qp(P, q, G, h, A, b, self.solver, initvals)

            logger.debug("Quadratic solver returned: %s" % solution)

        #Returns a dictionary with keys 'status', 'x', 's', 'y', 'z'.
        #
        #The default solver returns with status 'optimal' or 'unknown'.
        #The MOSEK solver can also return with status 'primal infeasible'
        #or 'dual infeasible'.
        #
        #If status is 'optimal', x, s, y, z are the primal and dual
        #optimal solutions.
        #
        #If status is 'primal infeasible', x = s = None and z, y are
        #a proof of primal infeasibility:
        #
        #    G'*z + A'*y = 0,  h'*z + b'*y = -1,  z >= 0.
        #
        #If status is 'dual infeasible', z = y = None, and x, s are
        #a proof of dual infeasibility:
        #
        #    P*x = 0,  q'*x = -1,  G*x + s = 0,  A*x = 0,  s >=0
        #
        #If status is 'unknown', x, y, s, z are None.

        return solution


    def _process_solution(self, Bf, buses, branches, generators,
                          nb, nl, ng, base_mva, solution, t_elapsed):
        """ Sets bus voltages angles, generator output powers and branch
            power flows using the solution.
        """
        self._solution = solution

        if solution["status"] == "optimal":
            logger.info("DC OPF completed in %.3fs." % t_elapsed)
        elif solution["status"] == "unknown":
            #From CVXOPT documentation:
            #Termination with status 'unknown' indicates that the algorithm
            #failed to find a solution that satisfies the specified tolerances.
            #In some cases, the returned solution may be fairly accurate.  If
            #the primal and dual infeasibilities, the gap, and the relative gap
            #are small, then x, y, s, z are close to optimal.
            logger.info("Unknown solution status found in %.3fs. The " \
                "solution may be fairly accurate. \nTry using a different " \
                "solver or relaxing the tolerances." % t_elapsed)
        elif solution["status"] == "error":
            logger.error("Exception occurred solving DC OPF.")
            return False
        else:
            logger.error("Non-convergent DC OPF.")
            return False

        x = solution["x"]

        # Bus voltage angles.
        v_angle = x[:nb]
#        print "Vphase:", v_angle
        for i, bus in enumerate(buses):
            bus.v_magnitude = 1.0
            bus.v_angle = v_angle[i]

        # Generator real power output.
        p = x[nb:nb + ng]
        for i, generator in enumerate(generators):
            generator.p = p[i] * base_mva
#            generator.p_despatch = p[i] * base_mva

        # Branch power flows.
        p_from = Bf * v_angle * base_mva
        p_to = -p_from
        for j, branch in enumerate(branches):
            branch.p_from = p_from[j]
            branch.p_to = p_to[j]

        # Update lambda and mu.
        # A Lagrange multiplier is the increase in the value of the objective
        # function due to the relaxation of a given constraint.
        eqlin = solution["y"]
        ineqlin = solution["z"]

        for i, bus in enumerate(buses):
            bus.p_lambda = eqlin[i + 1] / base_mva

        for j, branch in enumerate(branches):
            # TODO: Find multipliers for lower and upper bound constraints.
            branch.mu_s_from = 0.0
            branch.mu_s_to = 0.0

        for k, generator in enumerate(generators):
            generator.mu_pmin = ineqlin[k] / base_mva
            generator.mu_pmax = ineqlin[k + ng] / base_mva

        # Compute the objective function value.
        self._f = sum([g.total_cost(g.p) for g in generators])

        return True

# EOF -------------------------------------------------------------------------
