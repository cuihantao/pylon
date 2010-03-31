#------------------------------------------------------------------------------
# Pylon Tutorial "Optimal Power Flow"
#
# Author: Richard Lincoln, r.w.lincoln@gmail.com
#------------------------------------------------------------------------------

""" This tutorial provides a guide for solving an Optimal Power Flow problem
using Pylon.

First import the necessary components from Pylon."""

from pylon import Case, Bus, Branch, Generator, OPF

""" Import "sys" for writing to stdout. """
import sys

""" Create two generators, specifying their marginal cost. """
bus1 = Bus(p_demand=100.0)
g1 = Generator(bus1, p_min=0.0, p_max=80.0, p_cost=(0.0, 6.0, 0.0))
bus2 = Bus()
g2 = Generator(bus2, p_min=0.0, p_max=60.0, p_cost=(0.0, 9.0, 0.0))

""" Connect the two generator buses """
line = Branch(bus1, bus2, r=0.05)

""" and add it all to a case. """
case = Case(buses=[bus1, bus2], branches=[line], generators=[g1, g2])

""" Linearised DC optimal power flow """
dc = True

""" or non-linear AC optimal power flow may be selected. """
dc = False

""" Pass the case to the OPF routine and solve. """
OPF(case, dc).solve()

""" View the results as ReStructuredText. """
case.save_rst(sys.stdout)
