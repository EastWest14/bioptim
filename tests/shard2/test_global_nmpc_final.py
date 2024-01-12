"""
Test for file IO
"""
import os
import platform

import pytest
import numpy as np
from bioptim import Solver, MultiCyclicCycleSolutions, PhaseDynamics, SolutionMerge


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
def test_multi_cyclic_nmpc_get_final(phase_dynamics):
    def update_functions(_nmpc, cycle_idx, _sol):
        return cycle_idx < n_cycles_total  # True if there are still some cycle to perform

    from bioptim.examples.moving_horizon_estimation import multi_cyclic_nmpc as ocp_module

    bioptim_folder = os.path.dirname(ocp_module.__file__)

    n_cycles_simultaneous = 2
    n_cycles_to_advance = 1
    n_cycles_total = 3
    cycle_len = 20
    nmpc = ocp_module.prepare_nmpc(
        model_path=bioptim_folder + "/models/arm2.bioMod",
        cycle_len=cycle_len,
        cycle_duration=1,
        n_cycles_simultaneous=n_cycles_simultaneous,
        n_cycles_to_advance=n_cycles_to_advance,
        max_torque=50,
        phase_dynamics=phase_dynamics,
        expand_dynamics=True,
    )
    sol = nmpc.solve(
        update_functions,
        solver=Solver.IPOPT(),
        n_cycles_simultaneous=n_cycles_simultaneous,
        get_all_iterations=True,
        cycle_solutions=MultiCyclicCycleSolutions.ALL_CYCLES,
    )

    # Check some of the results
    states = sol[0].decision_states(to_merge=SolutionMerge.NODES)
    controls = sol[0].decision_controls(to_merge=SolutionMerge.NODES)
    q, qdot, tau = states["q"], states["qdot"], controls["tau"]

    # initial and final position
    np.testing.assert_equal(q.shape, (3, n_cycles_total * cycle_len + 1))
    np.testing.assert_almost_equal(q[:, 0], np.array((-12.56637061, 1.04359174, 1.03625065)))
    np.testing.assert_almost_equal(q[:, -1], np.array([1.37753244e-40, 1.04359174e00, 1.03625065e00]))

    # initial and final velocities
    np.testing.assert_almost_equal(qdot[:, 0], np.array((6.28293718, 2.5617072, -0.00942694)))
    np.testing.assert_almost_equal(qdot[:, -1], np.array([6.28293718, 2.41433059, -0.59773899]), decimal=5)

    # initial and final controls
    np.testing.assert_almost_equal(tau[:, 0], np.array((0.00992505, 4.88488618, 2.4400698)))
    np.testing.assert_almost_equal(tau[:, -1], np.array([-0.00992505, 5.19414727, 2.34022319]), decimal=4)

    # check time
    n_steps = nmpc.nlp[0].ode_solver.n_integration_steps
    time = sol[0].stepwise_time(to_merge=SolutionMerge.NODES)
    assert time.shape == (n_cycles_total * cycle_len * (n_steps + 1) + 1, 1)
    assert time[0] == 0
    np.testing.assert_almost_equal(time[-1], 3.0)

    # check some results of the second structure
    for s in sol[1]:
        states = s.stepwise_states(to_merge=SolutionMerge.NODES)
        q = states["q"]

        # initial and final position
        np.testing.assert_equal(q.shape, (3, 241))

        # check time
        time = s.stepwise_time(to_merge=SolutionMerge.NODES)
        assert time.shape == (241, 1)
        assert time[0] == 0
        np.testing.assert_almost_equal(time[-1], 2.0, decimal=4)

    # check some result of the third structure
    assert len(sol[2]) == 4

    for s in sol[2]:
        states = s.stepwise_states(to_merge=SolutionMerge.NODES)
        q = states["q"]

        # initial and final position
        np.testing.assert_equal(q.shape, (3, 121))

        # check time
        time = s.stepwise_time(to_merge=SolutionMerge.NODES)
        assert time.shape == (121, 1)
        assert time[0] == 0
        np.testing.assert_almost_equal(time[-1], 1.0, decimal=4)


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
def test_multi_cyclic_nmpc_not_get_final(phase_dynamics):
    if platform.system() != "Linux":
        # This is a long test and CI is already long for Windows and Mac
        return

    def update_functions(_nmpc, cycle_idx, _sol):
        return cycle_idx < n_cycles_total  # True if there are still some cycle to perform

    from bioptim.examples.moving_horizon_estimation import multi_cyclic_nmpc as ocp_module

    bioptim_folder = os.path.dirname(ocp_module.__file__)

    n_cycles_simultaneous = 2
    n_cycles_to_advance = 1
    n_cycles_total = 3
    cycle_len = 20
    nmpc = ocp_module.prepare_nmpc(
        model_path=bioptim_folder + "/models/arm2.bioMod",
        cycle_len=cycle_len,
        cycle_duration=1,
        n_cycles_simultaneous=n_cycles_simultaneous,
        n_cycles_to_advance=n_cycles_to_advance,
        max_torque=50,
        phase_dynamics=phase_dynamics,
    )
    sol = nmpc.solve(
        update_functions,
        solver=Solver.IPOPT(_max_iter=0),
        n_cycles_simultaneous=n_cycles_simultaneous,
        get_all_iterations=True,
        cycle_solutions=MultiCyclicCycleSolutions.FIRST_CYCLES,
    )

    # check some result of the third structure
    assert len(sol[2]) == 3

    np.testing.assert_almost_equal(sol[2][0].cost.toarray().squeeze(), 0.0002)
    np.testing.assert_almost_equal(sol[2][1].cost.toarray().squeeze(), 0.0002)
    np.testing.assert_almost_equal(sol[2][2].cost.toarray().squeeze(), 0.0002)
